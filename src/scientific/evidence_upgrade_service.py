# src/scientific/evidence_upgrade_service.py
import uuid
import json
from typing import Dict, List, Optional
from neo4j import Driver
from src.foundation.audit_service import log_action   # 改为从 audit_event 导入

# 证据等级升级映射
# L1/L2 → L3（单例临床验证）
# L3 → L4（多中心临床验证）
# L4 → L5（组织学习闭环）
LEVEL_UPGRADE_MAP = {
    'L3': ['L1', 'L2'],
    'L4': ['L3'],
    'L5': ['L4'],
}


# =============================================================
# 新增：证据升级提案相关函数（替代自动升级）
# =============================================================

def create_evidence_upgrade_proposal(
    driver: Driver,
    assay_id: str,
    source_case_id: str,
    proposed_level: str,
    reason: str,
    proposed_by: str = "system"
) -> str:
    """
    创建证据升级提案，状态为 pending_review。
    如果该 assay 已有 pending 提案，则抛出异常。
    """
    proposal_id = f"PROP-{uuid.uuid4().hex[:8].upper()}"
    with driver.session() as session:
        # 检查是否已有待审核提案（pending_review 或 needs_revision 都视为未完成）
        existing = session.run("""
            MATCH (p:EvidenceUpgradeProposal {assay_id: $assay_id})
            WHERE p.status IN ['pending_review', 'needs_revision']
            RETURN p
        """, assay_id=assay_id).single()
        if existing:
            raise ValueError(f"该 LysisAssay ({assay_id}) 已有待审核或需修改的升级提案")

        # 获取当前证据等级
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
                created_at: datetime()
            })
        """, proposal_id=proposal_id, assay_id=assay_id, source_case_id=source_case_id,
        current_level=current_level, proposed_level=proposed_level, reason=reason, proposed_by=proposed_by)
    return proposal_id


def review_evidence_upgrade_proposal(
    driver: Driver,
    proposal_id: str,
    reviewer_id: str,
    decision: str,  # 'approved' or 'rejected' or 'needs_revision'
    comment: str = None
) -> str:
    """
    审核提案：
    - approved: 执行升级并记录审计
    - rejected: 更新状态为 rejected，记录审计
    - needs_revision: 更新状态为 needs_revision，记录审计（不升级）
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
        review_id = f"REV-{uuid.uuid4().hex[:8].upper()}"
        session.run("""
            MATCH (p:EvidenceUpgradeProposal {proposal_id: $proposal_id})
            CREATE (r:Review {
                review_id: $review_id,
                target_domain: 'scientific',
                target_object_type: 'EvidenceUpgradeProposal',
                target_object_id: $proposal_id,
                reviewer_id: $reviewer_id,
                decision: $decision,
                comment: $comment,
                policy_version: 'v1',
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

        # 4. 根据决策执行不同操作（以下代码保持不变，仅示意）
        if decision == 'approved':
            # 更新 LysisAssay
            session.run("""
                MATCH (a:LysisAssay {assay_id: $assay_id})
                SET a.evidence_level = $proposed_level,
                    a.evidence_ref = CASE 
                        WHEN $case_id IN a.evidence_ref THEN a.evidence_ref
                        ELSE a.evidence_ref + $case_id
                    END,
                    a.last_upgraded_at = datetime()
            """, assay_id=assay_id, proposed_level=proposed_level, case_id=source_case_id)

            # 记录审计日志（使用 AuditEvent）
            log_action(
                driver,
                domain="scientific",
                action_type="EVIDENCE_UPGRADE_APPROVED",
                object_type="LysisAssay",
                object_id=assay_id,
                actor_id=reviewer_id,
                before_snapshot={"evidence_level": current_level},
                after_snapshot={"evidence_level": proposed_level},
                reason=f"升级提案 {proposal_id} 已批准"
            )
        elif decision == 'rejected':
            # 记录拒绝审计
            log_action(
                driver,
                domain="scientific",
                action_type="EVIDENCE_UPGRADE_REJECTED",
                object_type="EvidenceUpgradeProposal",
                object_id=proposal_id,
                actor_id=reviewer_id,
                before_snapshot={"status": "pending_review"},
                after_snapshot={"status": "rejected"},
                reason=comment or f"提案 {proposal_id} 被拒绝"
            )
        elif decision == 'needs_revision':
            # 记录需要修改的审计
            log_action(
                driver,
                domain="scientific",
                action_type="EVIDENCE_UPGRADE_NEEDS_REVISION",
                object_type="EvidenceUpgradeProposal",
                object_id=proposal_id,
                actor_id=reviewer_id,
                before_snapshot={"status": "pending_review"},
                after_snapshot={"status": "needs_revision"},
                reason=comment or f"提案 {proposal_id} 需要补充数据"
            )
        else:
            raise ValueError(f"不支持的决策: {decision}")

    return review_id


# =============================================================
# 保留原有函数，但修改其行为：不再自动升级，而是创建提案
# =============================================================

def curate_case_outcome(
    driver: Driver,
    case_id: str,
    treatment: Dict,   # {phage_ids: List[str], phage_names: List[str], cocktail_name: str}
    outcome: Dict,     # {clinical_outcome: str, microbiological_outcome: str}
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

    # 查找符合条件的 LysisAssay（使用名称匹配，避免 ID 不一致pending/passed）
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
            summary.append(f"⚠️ 未找到可升级的 LysisAssay（需要从 {source_levels_str} 升级到 {target_level}")
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
                        proposed_by="curation.py"
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
        phage_names = record['phage_names']   # 新增
    
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
            "phage_names": phage_names,   # 新增
            "cocktail_name": treatment_name
        },
        outcome={
            "clinical_outcome": clinical_outcome,
            "microbiological_outcome": microbiological_outcome
        },
        target_level=target_level,
        reviewer_id=reviewer_id
    )


# ==================== 便捷函数：批量策展 ====================
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