# src/scientific/evidence_upgrade_service.py
import uuid
import json
from typing import Dict, List, Optional
from neo4j import Driver
from src.foundation.audit_service import write_audit_event

# 证据等级升级映射
LEVEL_UPGRADE_MAP = {
    'L3': ['L1', 'L2'],
    'L4': ['L3'],
    'L5': ['L4'],
}


def _generate_proposal_id() -> str:
    """生成符合 PRD 7.2 的 EvidenceUpgradeProposal ID：SCI:PROPOSAL:<LOCAL_ID>"""
    local_id = uuid.uuid4().hex[:8].upper()
    return f"SCI:PROPOSAL:{local_id}"


def _generate_review_id(review_type: str) -> str:
    """
    生成符合 PRD 7.2 的 Review ID：FOUNDATION:REVIEW:<REVIEW_TYPE>-<LOCAL_ID>
    REVIEW_TYPE 取前8个字符，如 evidence_upgrade 取 EVIDENCE。
    """
    type_prefix = review_type[:8].upper()
    local_id = uuid.uuid4().hex[:8].upper()
    return f"FOUNDATION:REVIEW:{type_prefix}-{local_id}"


def create_evidence_upgrade_proposal(
    driver: Driver,
    assay_id: str,
    source_case_id: str,
    proposed_level: str,
    reason: str,
    proposed_by: str = "system",
    policy_version: str = "v1.0"
) -> str:
    """创建证据升级提案，状态为 pending_review。"""
    proposal_id = _generate_proposal_id()
    with driver.session() as session:
        existing = session.run("""
            MATCH (p:EvidenceUpgradeProposal {assay_id: $assay_id})
            WHERE p.status IN ['pending_review', 'needs_revision']
            RETURN p
        """, assay_id=assay_id).single()
        if existing:
            raise ValueError(f"该 LysisAssay ({assay_id}) 已有待审核或需修改的升级提案")
        current = session.run("""
            MATCH (a:LysisAssay {assay_id: $assay_id})
            RETURN a.evidence_level AS current_level
        """, assay_id=assay_id).single()
        current_level = current['current_level'] if current else None
        session.run("""
            CREATE (p:EvidenceUpgradeProposal {
                proposal_id: $proposal_id,
                assay_id: $assay_id,
                source_case_id: $source_case_id,
                current_level: $current_level,
                proposed_level: $proposed_level,
                reason: $reason,
                status: 'pending_review',
                proposed_by: $proposed_by,
                proposed_at: datetime(),
                created_at: datetime(),
                policy_version: $policy_version
            })
        """, proposal_id=proposal_id, assay_id=assay_id, source_case_id=source_case_id,
        current_level=current_level, proposed_level=proposed_level, reason=reason,
        proposed_by=proposed_by, policy_version=policy_version)
    return proposal_id


def review_evidence_upgrade_proposal(
    driver: Driver,
    proposal_id: str,
    reviewer_id: str,
    decision: str,  # 'approved' or 'rejected' or 'needs_revision'
    comment: str = None
) -> str:
    """
    审核证据升级提案：
    - approved: 执行升级并记录审计，提案状态变为 executed
    - rejected: 提案状态变为 rejected
    - needs_revision: 提案状态变为 needs_revision
    返回 review_id。
    """
    with driver.session() as session:
        # 1. 获取提案信息
        proposal = session.run("""
            MATCH (p:EvidenceUpgradeProposal {proposal_id: $proposal_id})
            RETURN p.assay_id AS assay_id,
                   p.proposed_level AS proposed_level,
                   p.status AS status,
                   p.current_level AS current_level,
                   p.source_case_id AS source_case_id
        """, proposal_id=proposal_id).single()
        if not proposal:
            raise ValueError(f"提案 {proposal_id} 不存在")
        if proposal['status'] not in ['pending_review', 'needs_revision']:
            raise ValueError(f"提案状态不是 pending_review 或 needs_revision，当前为 {proposal['status']}")

        assay_id = proposal['assay_id']
        proposed_level = proposal['proposed_level']
        current_level = proposal['current_level']
        source_case_id = proposal['source_case_id']

        # 2. 创建 Review 记录并建立 REVIEWS 关系
        review_id = _generate_review_id("evidence_upgrade")
        session.run("""
            MATCH (p:EvidenceUpgradeProposal {proposal_id: $proposal_id})
            CREATE (r:Review {
                review_id: $review_id,
                review_type: 'evidence_upgrade',
                target_domain: 'scientific',
                target_object_type: 'EvidenceUpgradeProposal',
                target_object_id: $proposal_id,
                reviewer_id: $reviewer_id,
                decision: $decision,
                comment: $comment,
                review_policy_version: 'v1.0',
                reviewed_at: datetime(),
                created_at: datetime()
            })
            CREATE (r)-[:REVIEWS]->(p)
        """, review_id=review_id, proposal_id=proposal_id, reviewer_id=reviewer_id,
        decision=decision, comment=comment)

        # 3. 更新提案状态
        session.run("""
            MATCH (p:EvidenceUpgradeProposal {proposal_id: $proposal_id})
            SET p.status = $decision,
                p.reviewed_at = datetime(),
                p.reviewer_id = $reviewer_id
        """, proposal_id=proposal_id, decision=decision, reviewer_id=reviewer_id)

        # 4. 根据决策执行不同操作
        if decision == 'approved':
            # 更新 LysisAssay 等级
            session.run("""
                MATCH (a:LysisAssay {assay_id: $assay_id})
                SET a.evidence_level = $proposed_level,
                    a.evidence_ref = CASE 
                        WHEN $case_id IN a.evidence_ref THEN a.evidence_ref
                        ELSE a.evidence_ref + $case_id
                    END,
                    a.last_upgraded_at = datetime()
            """, assay_id=assay_id, proposed_level=proposed_level, case_id=source_case_id)

            # 提案状态改为 executed
            session.run("""
                MATCH (p:EvidenceUpgradeProposal {proposal_id: $proposal_id})
                SET p.status = 'executed'
            """, proposal_id=proposal_id)

            # 审计日志
            write_audit_event(
                driver,
                action_type="DATA_CORRECTION",
                object_type="LysisAssay",
                object_id=assay_id,
                actor_id=reviewer_id,
                delta={"evidence_level": {"before": current_level, "after": proposed_level}},
                reason=f"升级提案 {proposal_id} 已批准并执行"
            )
        elif decision == 'rejected':
            write_audit_event(
                driver,
                action_type="STATUS_CHANGE",
                object_type="EvidenceUpgradeProposal",
                object_id=proposal_id,
                actor_id=reviewer_id,
                delta={"status": {"before": "pending_review", "after": "rejected"}},
                reason=comment or f"提案 {proposal_id} 被拒绝"
            )
        elif decision == 'needs_revision':
            write_audit_event(
                driver,
                action_type="STATUS_CHANGE",
                object_type="EvidenceUpgradeProposal",
                object_id=proposal_id,
                actor_id=reviewer_id,
                delta={"status": {"before": "pending_review", "after": "needs_revision"}},
                reason=comment or f"提案 {proposal_id} 需要补充数据"
            )
        else:
            raise ValueError(f"不支持的决策: {decision}")

    return review_id


def review_scientific_evidence_package(
    driver: Driver,
    package_id: str,
    reviewer_id: str,
    decision: str,
    comment: str = None
) -> str:
    """
    审核 ScientificEvidencePackage（scientific_package_review 类型）
    """
    with driver.session() as session:
        pkg = session.run("""
            MATCH (p:ScientificEvidencePackage {package_id: $package_id})
            RETURN p
        """, package_id=package_id).single()
        if not pkg:
            raise ValueError(f"证据包 {package_id} 不存在")
        
        review_id = _generate_review_id("package_review")
        session.run("""
            MATCH (pkg:ScientificEvidencePackage {package_id: $package_id})
            CREATE (r:Review {
                review_id: $review_id,
                review_type: 'scientific_package_review',
                target_domain: 'scientific',
                target_object_type: 'ScientificEvidencePackage',
                target_object_id: $package_id,
                reviewer_id: $reviewer_id,
                decision: $decision,
                comment: $comment,
                review_policy_version: 'v1.0',
                reviewed_at: datetime(),
                created_at: datetime()
            })
            CREATE (r)-[:REVIEWS]->(pkg)
        """, review_id=review_id, package_id=package_id,
        reviewer_id=reviewer_id, decision=decision, comment=comment)
        
        # 更新包状态
        new_status = 'approved' if decision == 'approved' else 'rejected'
        if decision == 'needs_revision':
            pass
        else:
            session.run("""
                MATCH (pkg:ScientificEvidencePackage {package_id: $package_id})
                SET pkg.status = $new_status,
                    pkg.review_status = $new_status,
                    pkg.updated_at = datetime()
            """, package_id=package_id, new_status=new_status)
        
        # 审计日志
        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="ScientificEvidencePackage",
            object_id=package_id,
            actor_id=reviewer_id,
            delta={"status": {"before": "draft", "after": new_status}},
            reason=comment or f"证据包审核 {decision}"
        )
    return review_id


def review_assay_qc(
    driver: Driver,
    assay_id: str,
    reviewer_id: str,
    decision: str,
    comment: str = None
) -> str:
    """
    审核 LysisAssay QC（assay_qc 类型）
    """
    with driver.session() as session:
        assay = session.run("""
            MATCH (a:LysisAssay {assay_id: $assay_id})
            RETURN a
        """, assay_id=assay_id).single()
        if not assay:
            raise ValueError(f"LysisAssay {assay_id} 不存在")
        
        review_id = _generate_review_id("assay_qc")
        session.run("""
            MATCH (a:LysisAssay {assay_id: $assay_id})
            CREATE (r:Review {
                review_id: $review_id,
                review_type: 'assay_qc',
                target_domain: 'scientific',
                target_object_type: 'LysisAssay',
                target_object_id: $assay_id,
                reviewer_id: $reviewer_id,
                decision: $decision,
                comment: $comment,
                review_policy_version: 'v1.0',
                reviewed_at: datetime(),
                created_at: datetime()
            })
            CREATE (r)-[:REVIEWS]->(a)
        """, review_id=review_id, assay_id=assay_id,
        reviewer_id=reviewer_id, decision=decision, comment=comment)
        
        new_qc_status = 'passed' if decision == 'passed' else 'failed'
        session.run("""
            MATCH (a:LysisAssay {assay_id: $assay_id})
            SET a.qc_status = $new_qc_status,
                a.updated_at = datetime()
        """, assay_id=assay_id, new_qc_status=new_qc_status)
        
        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="LysisAssay",
            object_id=assay_id,
            actor_id=reviewer_id,
            delta={"qc_status": {"before": assay["qc_status"], "after": new_qc_status}},
            reason=comment or f"QC 审核 {decision}"
        )
    return review_id


def curate_case_outcome(
    driver: Driver,
    case_id: str,
    treatment: Dict,
    outcome: Dict,
    target_level: str = 'L3',
    reviewer_id: str = "domain_expert_01"
) -> str:
    """
    更新 ClinicalCase 的治疗和结局字段。
    不再自动升级，而是为符合条件的 LysisAssay 创建升级提案（仅限该病例实际使用的噬菌体）。
    返回提案创建摘要。
    """
    if not outcome.get('clinical_outcome') or not outcome.get('microbiological_outcome'):
        return "⚠️ 病例结局字段缺失，无法创建升级提案。请补充 clinical_outcome 和 microbiological_outcome。"

    summary = []
    source_levels = LEVEL_UPGRADE_MAP.get(target_level, ['L1', 'L2'])
    source_levels_str = ', '.join([f"'{l}'" for l in source_levels])

    # 更新 ClinicalCase
    update_case_query = """
    MATCH (c:ClinicalCase {case_id: $case_id})
    SET c.phage_treatment = $phage_treatment,
        c.clinical_outcome = $clinical_outcome,
        c.microbiological_outcome = $microbiological_outcome,
        c.curated_by = 'curation.py',
        c.curation_date = date()
    RETURN c.case_id
    """
    with driver.session() as session:
        session.run(update_case_query,
                    case_id=case_id,
                    phage_treatment=treatment.get('cocktail_name', ''),
                    clinical_outcome=outcome.get('clinical_outcome', ''),
                    microbiological_outcome=outcome.get('microbiological_outcome', ''))
        summary.append(f"✅ 病例 {case_id} 已更新结局")

    # 查找符合条件的 LysisAssay
    if treatment.get('phage_names'):
        phage_names = treatment['phage_names']
        find_query = f"""
        MATCH (c:ClinicalCase {{case_id: $case_id}})
        MATCH (c)-[:HAS_ISOLATE]->(h:HostStrain)
        MATCH (a:LysisAssay)-[:TESTED_AGAINST]->(h)
        MATCH (ph:Phage)-[:USED_IN]->(a)
        WHERE a.evidence_level IN [{source_levels_str}]
        AND a.result = 'Lytic'
        AND a.qc_status in ['pending', 'passed']
        AND ph.name IN $phage_names
        RETURN a.assay_id AS assay_id,
            a.evidence_level AS old_level,
            a.evidence_ref AS old_ref
        """
        with driver.session() as session:
            records = session.run(find_query, case_id=case_id, phage_names=phage_names).data()

        if not records:
            summary.append(f"⚠️ 未找到可升级的 LysisAssay（需要从 {source_levels_str} 升级到 {target_level}）")
        else:
            proposal_ids = []
            for rec in records:
                assay_id = rec['assay_id']
                old_level = rec['old_level']
                try:
                    proposal_id = create_evidence_upgrade_proposal(
                        driver,
                        assay_id=assay_id,
                        source_case_id=case_id,
                        proposed_level=target_level,
                        reason=f"基于病例 {case_id} 的临床结局 ({outcome.get('clinical_outcome')}) 和微生物学结局 ({outcome.get('microbiological_outcome')})，建议升级证据等级。",
                        proposed_by="curation.py",
                        policy_version="v1.0"
                    )
                    proposal_ids.append(proposal_id)
                except ValueError as e:
                    proposal_ids.append(f"跳过: {e}")

            summary.append(f"✅ 已创建 {len([p for p in proposal_ids if not p.startswith('跳过')])} 个升级提案（待审核）。提案ID: {', '.join(proposal_ids)}")
    else:
        summary.append("⚠️ 未提供 phage_names，无法筛选实际使用的噬菌体")

    return "\n".join(summary)


def curate_case_by_id(
    driver: Driver,
    case_id: str,
    clinical_outcome: str,
    microbiological_outcome: str,
    target_level: str = 'L3',
    reviewer_id: str = "domain_expert_01"
) -> str:
    """
    自动根据病例 ID 策展：更新病例结局，并自动为该病例关联的 LysisAssay 创建升级提案（如果满足条件）。
    返回创建提案的结果摘要。
    注意：不再自动升级，需人工审核提案后方可执行升级。
    """
    # 1. 查询该病例使用的噬菌体 ID 和名称
    with driver.session() as session:
        result = session.run("""
            MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(ph:Phage)
            RETURN collect(ph.phage_id) AS phage_ids, collect(ph.name) AS phage_names
        """, case_id=case_id)
        record = result.single()
        if not record or not record['phage_ids']:
            return f"⚠️ 病例 {case_id} 没有关联的噬菌体，请先通过 TREATED_WITH 关联。"
        
        phage_ids = record['phage_ids']
        phage_names = record['phage_names']
    
    # 2. 查询该病例当前的 phage_treatment（用于 cocktail_name）
    with driver.session() as session:
        result = session.run("""
            MATCH (c:ClinicalCase {case_id: $case_id})
            RETURN c.phage_treatment AS treatment
        """, case_id=case_id)
        record = result.single()
        treatment_name = record['treatment'] if record and record['treatment'] else f"{case_id} 治疗方案"
    
    # 3. 调用修改后的 curate_case_outcome（传入 phage_names）
    return curate_case_outcome(
        driver,
        case_id=case_id,
        treatment={
            "phage_ids": phage_ids,
            "phage_names": phage_names,
            "cocktail_name": treatment_name
        },
        outcome={
            "clinical_outcome": clinical_outcome,
            "microbiological_outcome": microbiological_outcome
        },
        target_level=target_level,
        reviewer_id=reviewer_id
    )


def batch_curate_cases(
    driver: Driver,
    cases: List[Dict],
    target_level: str = 'L3',
    reviewer_id: str = "domain_expert_01"
) -> List[str]:
    """
    批量策展多个病例。
    
    Args:
        driver: Neo4j 驱动
        cases: 病例列表，每个元素包含 case_id, clinical_outcome, microbiological_outcome
        target_level: 目标证据等级，默认 L3
        reviewer_id: 审核专家ID，默认为 domain_expert_01
    
    Returns:
        List[str]: 每个病例的策展摘要
    """
    summaries = []
    for case in cases:
        summary = curate_case_by_id(
            driver,
            case_id=case['case_id'],
            clinical_outcome=case['clinical_outcome'],
            microbiological_outcome=case['microbiological_outcome'],
            target_level=target_level,
            reviewer_id=reviewer_id
        )
        summaries.append(summary)
    return summaries