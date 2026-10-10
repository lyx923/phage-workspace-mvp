# src/ci/competitor_profile.py
"""
CompetitorProfile / CompetitorAssessment / Landscape / PatentFamily
合并服务（PRD 8.3 / 13 / 7.3）

包含四个部分：
    Part 1: CompetitorProfile    —— 构建组织完整档案
    Part 2: CompetitorAssessment —— 竞争评估
    Part 3: Landscape            —— 项目 / 策略 / 白空间格局分析
    Part 4: PatentFamily         —— 专利族管理
"""

# ==================================================================
# Part 1: CompetitorProfile (原 competitor_profile.py)
# ==================================================================
from typing import Dict, List, Optional
from neo4j import Driver
from datetime import datetime
import uuid
from src.shared.audit_service import write_audit_event


def build_competitor_profile(driver: Driver, organization_id: str,
                             as_of_date: Optional[str] = None) -> Dict:
    """
    构建一个组织的完整竞争档案。

    汇总：
        - 组织基础信息
        - 所有研发项目（含目标病原）
        - 所有情报事件（含影响项目）
        - 所有专利族（含关联项目）
        - 所有临床试验（含关联项目）
        - 统计数据 + 数据缺口提示

    Args:
        driver: Neo4j 驱动
        organization_id: 组织 ID
        as_of_date: 信息截止日期（默认今天）

    Returns:
        Dict: 组织档案，若组织不存在则返回 {"error": ...}
    """
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")

    with driver.session() as session:
        # 1. 组织基础信息
        org_result = session.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.organization_id AS id, o.canonical_name AS name,
                   o.aliases AS aliases, o.organization_type AS org_type,
                   o.headquarters_country AS country, o.website AS website,
                   o.company_status AS status, o.public_or_private AS public_private,
                   o.description AS description, o.review_status AS review_status,
                   o.last_verified_at AS last_verified
        """, oid=organization_id).single()
        if not org_result:
            return {"error": f"组织 {organization_id} 不存在"}
        org_data = dict(org_result)

        # 2. 研发项目
        programs = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            OPTIONAL MATCH (d)-[:TARGETS_PATHOGEN]->(p:Pathogen)
            WITH d, COLLECT(DISTINCT {pathogen_id: p.pathogen_id, species: p.species}) AS target_pathogens
            RETURN d.program_id AS program_id, d.canonical_name AS name,
                   d.program_type AS program_type, d.development_stage AS stage,
                   d.program_status AS status, d.modality AS modality,
                   d.review_status AS review_status, target_pathogens
            ORDER BY d.created_at DESC
        """, oid=organization_id)
        program_list = [dict(record) for record in programs]

        # 3. 情报事件
        events = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:INVOLVES]-(e:IntelligenceEvent)
            WHERE e.organization_id = $oid
            OPTIONAL MATCH (e)-[:AFFECTS]->(d:DevelopmentProgram)
            RETURN e.event_id AS event_id, e.event_type AS event_type,
                   e.title AS title, e.factual_summary AS summary,
                   e.event_date AS event_date, e.published_at AS published_at,
                   e.confidence AS confidence, e.materiality AS materiality,
                   e.review_status AS review_status,
                   d.canonical_name AS affected_program
            ORDER BY e.event_date DESC
        """, oid=organization_id)
        event_list = [dict(record) for record in events]

        # 4. 专利族
        patents = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:OWNS_PATENT]->(pf:PatentFamily)
            OPTIONAL MATCH (dp:DevelopmentProgram)-[:COVERED_BY]->(pf)
            WITH pf, collect(DISTINCT dp.canonical_name) AS programs
            RETURN pf.patent_family_id AS patent_family_id, pf.title AS title,
                   pf.priority_date AS priority_date,
                   pf.publication_numbers AS publication_numbers,
                   pf.jurisdictions AS jurisdictions, pf.legal_status AS legal_status,
                   pf.claim_scope_summary AS claim_scope_summary, programs
            ORDER BY pf.priority_date DESC
        """, oid=organization_id)
        patent_list = [dict(record) for record in patents]

        # 5. 临床试验
        trials = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:SPONSORS]->(ct:ClinicalTrial)
            OPTIONAL MATCH (dp:DevelopmentProgram)-[:HAS_TRIAL]->(ct)
            WITH ct, collect(DISTINCT dp.canonical_name) AS programs
            RETURN ct.trial_id AS trial_id, ct.nct_id AS nct_id, ct.title AS title,
                   ct.phase AS phase, ct.status AS status,
                   ct.indication AS indication, ct.start_date AS start_date,
                   ct.completion_date AS completion_date,
                   ct.enrollment AS enrollment, programs
            ORDER BY ct.start_date DESC
        """, oid=organization_id)
        trial_list = [dict(record) for record in trials]

        # 6. 统计
        stats = {
            "total_programs": len(program_list),
            "active_programs": sum(1 for p in program_list if p.get('status') == 'active'),
            "total_events": len(event_list),
            "recent_events": sum(1 for e in event_list
                                 if e.get('event_date') and e['event_date'] > "2026-01-01"),
            "pathogens_covered": list(set(
                p['species'] for prog in program_list
                for p in prog.get('target_pathogens', []) if p.get('species')
            )),
            "total_patents": len(patent_list),
            "total_trials": len(trial_list),
        }

        # 7. 数据缺口
        gaps = []
        if not program_list:
            gaps.append("无公开研发项目信息")
        if not event_list:
            gaps.append("无近期情报事件")
        if not org_data.get('website'):
            gaps.append("缺少官方网站")
        if not org_data.get('description'):
            gaps.append("缺少公司描述")
        if not org_data.get('public_private') or org_data['public_private'] == 'unknown':
            gaps.append("公司类型（上市/私有）未确认")
        if not patent_list:
            gaps.append("尚未收集到专利族信息")
        if not trial_list:
            gaps.append("尚未收集到临床试验信息")

        return {
            "organization": org_data,
            "active_programs": program_list,
            "recent_events": event_list,
            "patent_families": patent_list,
            "clinical_trials": trial_list,
            "target_pathogens": stats["pathogens_covered"],
            "statistics": stats,
            "data_gaps": gaps,
            "as_of_date": as_of_date,
            "generated_at": datetime.now().isoformat(),
        }


def list_organizations(driver: Driver) -> List[Dict]:
    """列出所有组织（ID / 名称 / 类型 / 国家）。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (o:Organization)
            RETURN o.organization_id AS id, o.canonical_name AS name,
                   o.organization_type AS type, o.headquarters_country AS country
            ORDER BY o.canonical_name
        """)
        return [dict(record) for record in result]


# ==================================================================
# Part 2: CompetitorAssessment (原 competitor_assessment.py)
# ==================================================================

def generate_assessment_id() -> str:
    """生成竞争评估 ID（格式：CI:ASSESS:XXXXXXXX）。"""
    return f"CI:ASSESS:{uuid.uuid4().hex[:8].upper()}"


# subject_type → (Neo4j label, id 属性名, name 属性名)
_SUBJECT_NAME_MAP = {
    "organization": ("Organization", "organization_id", "canonical_name"),
    "program":      ("DevelopmentProgram", "program_id", "canonical_name"),
    "event":        ("IntelligenceEvent", "event_id", "title"),
}


def _resolve_subject_name(driver, subject_type, subject_id):
    """
    根据 subject_type + subject_id 查回可读名称，用于替换 summary 中的 ID。
    """
    if not subject_id:
        return subject_id
    cfg = _SUBJECT_NAME_MAP.get(subject_type)
    if not cfg:
        return subject_id
    label, id_prop, name_prop = cfg
    try:
        with driver.session() as s:
            r = s.run(
                f"MATCH (n:{label} {{`{id_prop}`: $sid}}) RETURN n.{name_prop} AS name LIMIT 1",
                sid=subject_id,
            ).single()
            if r and r.get("name"):
                return r["name"]
    except Exception:
        pass
    return subject_id


def _humanize_summary(driver, subject_type, subject_id, summary):
    """
    将 summary 中出现的 subject_id 替换为可读名称，便于阅读。
    """
    if not summary:
        return summary
    try:
        name = _resolve_subject_name(driver, subject_type, subject_id)
        if name and name != subject_id:
            summary = summary.replace(subject_id, name)
    except Exception:
        pass
    return summary


def create_competitor_assessment(
    driver: Driver, assessment_type: str, subject_type: str, subject_id: str,
    impact_area: str, impact_level: str, assessment_summary: str,
    confidence: str = "medium", analyst_id: str = "unknown",
    time_horizon: Optional[str] = None,
    assumptions: Optional[List[str]] = None, unknowns: Optional[List[str]] = None,
    valid_until: Optional[str] = None, actor_id: str = "system",
) -> str:
    """
    创建竞争评估（CompetitorAssessment）。

    会先校验 subject_type + subject_id 对应的对象是否存在，
    然后创建节点并建立 ASSESSES 关系。

    Args:
        assessment_type: 评估类型
        subject_type: organization / program / event
        subject_id: 被评估对象的 ID
        impact_area / impact_level: 影响领域 / 影响级别
        assessment_summary: 评估摘要
        confidence: 置信度
        analyst_id: 分析师 ID
        time_horizon: 时间视野
        assumptions / unknowns: 假设 / 未知项
        valid_until: 有效期
        actor_id: 操作者

    Returns:
        str: assessment_id
    """
    assessment_id = generate_assessment_id()
    assumptions = assumptions or []
    unknowns = unknowns or []
    if subject_type not in _SUBJECT_NAME_MAP:
        raise ValueError(
            f"不支持的 subject_type: {subject_type}，可选: {list(_SUBJECT_NAME_MAP.keys())}"
        )
    label, id_prop, _ = _SUBJECT_NAME_MAP[subject_type]
    assessment_summary = _humanize_summary(driver, subject_type, subject_id, assessment_summary)

    with driver.session() as session:
        # 校验被评估对象存在
        check_query = f"MATCH (n:{label} {{`{id_prop}`: $sid}}) RETURN n"
        target = session.run(check_query, sid=subject_id).single()
        if not target:
            raise ValueError(f"{subject_type} 对象 {subject_id} 不存在")

        # 创建评估节点
        session.run(
            f"""
            CREATE (ca:CompetitorAssessment {{
                assessment_id: $assessment_id, assessment_type: $assessment_type,
                subject_type: $subject_type, subject_id: $subject_id,
                impact_area: $impact_area, impact_level: $impact_level,
                time_horizon: $time_horizon, assessment_summary: $summary,
                assumptions: $assumptions, unknowns: $unknowns,
                confidence: $confidence, analyst_id: $analyst_id,
                valid_until: $valid_until, review_status: 'draft',
                assessed_at: datetime(), created_at: datetime(), updated_at: datetime()
            }})
            """,
            assessment_id=assessment_id, assessment_type=assessment_type,
            subject_type=subject_type, subject_id=subject_id,
            impact_area=impact_area, impact_level=impact_level,
            time_horizon=time_horizon, summary=assessment_summary,
            assumptions=assumptions, unknowns=unknowns,
            confidence=confidence, analyst_id=analyst_id, valid_until=valid_until,
        )
        # 建立 ASSESSES 关系
        session.run(
            f"""
            MATCH (ca:CompetitorAssessment {{assessment_id: $assessment_id}})
            MATCH (n:{label} {{`{id_prop}`: $subject_id}})
            CREATE (ca)-[:ASSESSES]->(n)
            """,
            assessment_id=assessment_id, subject_id=subject_id,
        )
        write_audit_event(
            driver, action_type="CREATE",
            object_type="CompetitorAssessment", object_id=assessment_id,
            actor_id=actor_id,
            delta={"assessment_type": assessment_type, "subject_type": subject_type,
                   "subject_id": subject_id, "impact_level": impact_level},
            reason=f"分析人员 {analyst_id} 创建了 {assessment_type} 评估",
        )
        return assessment_id


def get_assessment(driver, assessment_id):
    """按 ID 查询竞争评估。"""
    with driver.session() as session:
        result = session.run(
            "MATCH (ca:CompetitorAssessment {assessment_id: $aid}) RETURN ca",
            aid=assessment_id,
        ).single()
        return dict(result["ca"]) if result else None


def get_assessments_for_subject(driver, subject_type, subject_id, limit=50):
    """查询某对象的所有竞争评估，按时间倒序。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (ca:CompetitorAssessment {subject_type: $stype, subject_id: $sid})
            RETURN ca ORDER BY ca.assessed_at DESC LIMIT $limit
        """, stype=subject_type, sid=subject_id, limit=limit)
        return [dict(record["ca"]) for record in result]


def update_assessment_review_status(driver, assessment_id, new_status,
                                    reviewer_id, comment=None, actor_id="system"):
    """
    更新竞争评估的审核状态。

    Args:
        new_status: draft / reviewed / approved
    """
    valid_statuses = ["draft", "reviewed", "approved"]
    if new_status not in valid_statuses:
        raise ValueError(f"状态必须是 {valid_statuses} 之一")

    with driver.session() as session:
        check = session.run(
            "MATCH (ca:CompetitorAssessment {assessment_id: $aid}) RETURN ca",
            aid=assessment_id,
        ).single()
        if not check:
            raise ValueError(f"评估 {assessment_id} 不存在")
        session.run("""
            MATCH (ca:CompetitorAssessment {assessment_id: $aid})
            SET ca.review_status = $status, ca.reviewed_by = $reviewer,
                ca.review_comment = $comment,
                ca.reviewed_at = datetime(), ca.updated_at = datetime()
        """, aid=assessment_id, status=new_status,
             reviewer=reviewer_id, comment=comment)
        write_audit_event(
            driver, action_type="STATUS_CHANGE",
            object_type="CompetitorAssessment", object_id=assessment_id,
            actor_id=actor_id,
            delta={"review_status": new_status, "reviewer_id": reviewer_id},
            reason=comment or f"审核状态更新为 {new_status}",
        )
        return True


# ==================================================================
# Part 3: Landscape
# ==================================================================
from datetime import datetime as _dt
from typing import Any, Dict, List, Optional

# 默认对比维度
DEFAULT_COMPARISON_DIMENSIONS = [
    "target_pathogen", "clinical_indication", "development_stage",
    "modality", "engineering_strategy", "trial_status",
    "patent_coverage", "evidence_maturity",
]
# 证据成熟度顺序
MATURITY_ORDER = {"conceptual": 0, "in_vitro": 1, "in_vivo": 2, "clinical": 3}
# 白空间声明（必须随结果一起返回，避免误读）
WHITE_SPACE_DISCLAIMER = (
    'White space 表示在当前已收集、截至指定日期的公开证据中覆盖较少的区域。'
    '它不等于：市场上绝对无人布局、不存在未公开项目、该区域必然有商业价值、'
    '该区域不存在专利风险。'
)


def _today() -> str:
    """返回今天的 YYYY-MM-DD 字符串。"""
    return _dt.now().strftime("%Y-%m-%d")


def _max_maturity(levels):
    """返回列表中最高的证据成熟度（按 MATURITY_ORDER）。"""
    if not levels:
        return "conceptual"
    return max(levels, key=lambda x: MATURITY_ORDER.get(x, 0))


def _count_by(items, key):
    """按某字段对列表计数，缺失值归为 'unknown'。"""
    out = {}
    for it in items:
        v = it.get(key) or "unknown"
        out[v] = out.get(v, 0) + 1
    return out


def _build_matrix(programs):
    """
    构建 strategy × pathogen 的覆盖矩阵。

    Returns:
        (x_axis, y_axis, cells)：x 轴为工程策略类型，y 轴为病原物种，
        cells 为二维数组，每个单元格含 program_ids 和 count。
    """
    x_axis = sorted({s for p in programs for s in (p.get("engineering_strategy") or [])})
    y_axis = sorted({s for p in programs for s in (p.get("target_pathogen") or [])})
    cells = []
    for st in x_axis:
        row = []
        for sp in y_axis:
            progs = [p["program_id"] for p in programs
                     if st in (p.get("engineering_strategy") or [])
                     and sp in (p.get("target_pathogen") or [])]
            row.append({"strategy_type": st, "pathogen_species": sp,
                        "program_ids": progs, "count": len(progs)})
        cells.append(row)
    return x_axis, y_axis, cells


def compare_competitor_programs(driver, program_ids, comparison_dimensions=None):
    """
    对比多个研发项目。

    对每个 program_id 收集：
        - 目标病原 / 临床适应症 / 发展阶段 / 模态
        - 工程策略 / 试验状态 / 专利覆盖 / 证据成熟度
    然后生成 strategy × pathogen 矩阵。

    Args:
        program_ids: 项目 ID 列表
        comparison_dimensions: 自定义对比维度（默认 DEFAULT_COMPARISON_DIMENSIONS）

    Returns:
        Dict: {as_of_date, dimensions, programs, matrix, notes}
    """
    if not program_ids:
        raise ValueError("program_ids 不能为空")
    dims = comparison_dimensions or DEFAULT_COMPARISON_DIMENSIONS
    dims = [d for d in dims if d in DEFAULT_COMPARISON_DIMENSIONS]
    programs = []

    with driver.session() as s:
        for pid in program_ids:
            # 基础信息
            base = s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                OPTIONAL MATCH (o:Organization)-[:DEVELOPS]->(d)
                RETURN d.program_id AS program_id, d.canonical_name AS canonical_name,
                       d.development_stage AS development_stage,
                       d.program_status AS program_status, d.modality AS modality,
                       o.canonical_name AS organization
            """, pid=pid).single()
            if not base:
                continue
            row = {"program_id": base["program_id"],
                   "canonical_name": base["canonical_name"],
                   "organization": base["organization"]}

            # 目标病原
            pathogens = [r["species"] for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})-[:TARGETS_PATHOGEN]->(p:Pathogen)
                RETURN DISTINCT p.species AS species
            """, pid=pid)]
            row["target_pathogen"] = pathogens

            # 临床适应症
            indications = [r["indication"] for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})-[:HAS_TRIAL]->(ct:ClinicalTrial)
                WHERE ct.indication IS NOT NULL AND ct.indication <> ''
                RETURN DISTINCT ct.indication AS indication
            """, pid=pid)]
            row["clinical_indication"] = indications
            row["development_stage"] = base["development_stage"]
            row["modality"] = base["modality"]

            # 工程策略
            strategies = [r["stype"] for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d)
                OPTIONAL MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
                WITH collect(DISTINCT es.strategy_type) AS alls
                UNWIND alls AS stype
                WITH DISTINCT stype WHERE stype IS NOT NULL
                RETURN stype
            """, pid=pid)]
            row["engineering_strategy"] = strategies

            # 试验状态
            trials = [dict(r) for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})-[:HAS_TRIAL]->(ct:ClinicalTrial)
                RETURN ct.trial_id AS trial_id, ct.nct_id AS nct_id,
                       ct.phase AS phase, ct.status AS status
            """, pid=pid)]
            row["trial_status"] = {
                "total": len(trials),
                "by_status": _count_by(trials, "status"),
                "by_phase": _count_by(trials, "phase"),
                "active": [t for t in trials if t["status"] in
                           ("recruiting", "active", "not_yet_recruiting")],
            }

            # 专利覆盖
            patents = [dict(r) for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})-[:COVERED_BY]->(pf:PatentFamily)
                RETURN pf.patent_family_id AS pid, pf.legal_status AS status,
                       pf.jurisdictions AS jurisdictions
            """, pid=pid)]
            row["patent_coverage"] = {
                "total_families": len(patents),
                "by_legal_status": _count_by(patents, "status"),
            }

            # 证据成熟度
            maturities = [r["m"] for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d)
                OPTIONAL MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(ec)
                WHERE ta.evidence_maturity IS NOT NULL
                RETURN DISTINCT ta.evidence_maturity AS m
            """, pid=pid)]
            row["evidence_maturity"] = _max_maturity(maturities)

            # 只保留用户请求的维度
            filtered = {"program_id": row["program_id"],
                        "canonical_name": row["canonical_name"],
                        "organization": row["organization"]}
            for d in dims:
                filtered[d] = row.get(d)
            programs.append(filtered)

    x_axis, y_axis, cells = _build_matrix(programs)
    return {
        "as_of_date": _today(),
        "dimensions": dims,
        "programs": programs,
        "matrix": {"x_axis": x_axis, "y_axis": y_axis, "cells": cells},
        "notes": ["本矩阵仅基于当前图谱中已结构化的项目维度，不含未公开信息。"],
    }


def map_engineering_landscape(driver, target_pathogen_id=None,
                              engineering_strategy_ids=None, as_of_date=None):
    """
    绘制工程化格局。

    - 按目标病原 / 工程策略筛选构建体
    - 拉取相关 claims / results / assessments / patents
    - 识别白空间与不确定性
    """
    as_of_date = as_of_date or _today()
    strategy_ids = engineering_strategy_ids or []

    with driver.session() as s:
        constructs = [dict(r) for r in s.run("""
            MATCH (ec:EngineeredPhageConstruct)
            WHERE ($pid IS NULL OR EXISTS {
                MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
            })
            AND ($sids = [] OR EXISTS {
                MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
                WHERE es.strategy_id IN $sids
            })
            OPTIONAL MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
            OPTIONAL MATCH (d)<-[:DEVELOPS]-(o:Organization)
            WITH ec, collect(DISTINCT es.strategy_type) AS strategies,
                 collect(DISTINCT p.species) AS pathogens,
                 collect(DISTINCT d.canonical_name) AS programs,
                 collect(DISTINCT o.canonical_name) AS orgs
            RETURN ec.construct_id AS construct_id, ec.public_name AS public_name,
                   ec.construct_status AS construct_status,
                   strategies, pathogens, programs, orgs
            ORDER BY ec.created_at DESC
        """, pid=target_pathogen_id, sids=strategy_ids)]

        construct_ids = [c["construct_id"] for c in constructs]
        # 关联 claims / results / assessments / patents（仅当有构建体时查询）
        claims = [dict(r) for r in s.run("""
            MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec:EngineeredPhageConstruct)
            WHERE ec.construct_id IN $cids
            RETURN tc.claim_id AS claim_id, tc.claim_type AS claim_type,
                   tc.claim_text AS claim_text, tc.claim_status AS claim_status,
                   tc.review_status AS review_status,
                   ec.construct_id AS construct_id
        """, cids=construct_ids)] if construct_ids else []

        results = [dict(r) for r in s.run("""
            MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
            WHERE ec.construct_id IN $cids
            RETURN tr.result_id AS result_id, tr.result_type AS result_type,
                   tr.study_context AS study_context,
                   tr.outcome_direction AS outcome_direction,
                   ec.construct_id AS construct_id
        """, cids=construct_ids)] if construct_ids else []

        maturities = [r["m"] for r in s.run("""
            MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(ec:EngineeredPhageConstruct)
            WHERE ec.construct_id IN $cids
            RETURN DISTINCT ta.evidence_maturity AS m
        """, cids=construct_ids)] if construct_ids else []

        # 成熟度分布
        distribution = {"conceptual": 0, "in_vitro": 0, "in_vivo": 0, "clinical": 0}
        for m in maturities:
            if m in distribution:
                distribution[m] += 1

        patents = [dict(r) for r in s.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
                  -[:COVERED_BY]->(pf:PatentFamily)
            WHERE ec.construct_id IN $cids
            RETURN DISTINCT pf.patent_family_id AS patent_family_id,
                   pf.title AS title, pf.legal_status AS legal_status
        """, cids=construct_ids)] if construct_ids else []

    organizations = sorted({o for c in constructs for o in (c.get("orgs") or [])})
    programs = sorted({p for c in constructs for p in (c.get("programs") or [])})
    white_spaces = _detect_white_spaces(driver, target_pathogen_id, strategy_ids)
    uncertainties = _build_uncertainties(constructs, claims, results, distribution)

    return {
        "as_of_date": as_of_date,
        "filters": {"target_pathogen_id": target_pathogen_id,
                    "engineering_strategy_ids": strategy_ids},
        "known_constructs": constructs,
        "organizations": organizations,
        "programs": programs,
        "claims": claims,
        "results": results,
        "evidence_maturity_distribution": distribution,
        "patent_families": patents,
        "white_spaces": white_spaces,
        "uncertainties": uncertainties,
        "disclaimer": WHITE_SPACE_DISCLAIMER,
    }


def _detect_white_spaces(driver, target_pathogen_id, strategy_ids):
    """
    内部函数：检测 strategy × pathogen 组合中构建体数量为 0 的白空间。
    """
    with driver.session() as s:
        if strategy_ids:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy) WHERE es.strategy_id IN $sids
                RETURN es.strategy_id AS sid, es.strategy_type AS stype
            """, sids=strategy_ids)]
        else:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy)
                RETURN es.strategy_id AS sid, es.strategy_type AS stype LIMIT 20
            """)]
        if target_pathogen_id:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen {pathogen_id: $pid})
                RETURN p.pathogen_id AS pid, p.species AS species
            """, pid=target_pathogen_id)]
        else:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen) RETURN p.pathogen_id AS pid, p.species AS species LIMIT 20
            """)]
        white = []
        for st in strategies:
            for pa in pathogens:
                cnt = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    RETURN count(DISTINCT ec) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]
                if cnt == 0:
                    white.append({"strategy_type": st["stype"],
                                  "pathogen_species": pa["species"],
                                  "construct_count": 0, "coverage": "empty"})
    return white


def _build_uncertainties(constructs, claims, results, distribution):
    """
    内部函数：基于构建体 / 主张 / 结果 / 成熟度分布，生成不确定性提示列表。
    """
    u = []
    if not constructs:
        u.append("当前范围内无公开构建体")
    if claims and not results:
        u.append("存在技术主张但缺少实验结果")
    if distribution.get("clinical", 0) == 0 and distribution.get("in_vivo", 0) == 0:
        u.append("当前证据成熟度以体外为主，临床转化存在不确定性")
    if any(c.get("construct_status") == "proposed" for c in constructs):
        u.append("部分构建体仅处于 proposed 状态，未见实测数据")
    return u


def compare_engineering_strategies(driver, strategy_ids):
    """
    对比多个工程策略。

    对每个策略收集：
        - 基础信息 / 预期能力
        - 相关构建体 / 结果 / 评估 / 组织 / 专利
    """
    if not strategy_ids:
        raise ValueError("strategy_ids 不能为空")
    strategies = []
    with driver.session() as s:
        for sid in strategy_ids:
            base = s.run("""
                MATCH (es:EngineeringStrategy {strategy_id: $sid})
                RETURN es.strategy_id AS sid, es.strategy_type AS stype,
                       es.description AS desc, es.evidence_maturity AS em
            """, sid=sid).single()
            if not base:
                continue
            # 相关构建体
            constructs = [dict(r) for r in s.run("""
                MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $sid})
                RETURN ec.construct_id AS cid, ec.public_name AS name,
                       ec.construct_status AS status,
                       ec.intended_effects AS effects
            """, sid=sid)]
            cids = [c["cid"] for c in constructs]

            # 预期能力
            capabilities = []
            for c in constructs:
                capabilities.extend(c.get("effects") or [])
            capabilities = sorted(set(capabilities))

            # 相关结果
            results = [dict(r) for r in s.run("""
                MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
                      -[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                RETURN tr.result_type AS result_type,
                       tr.study_context AS study_context,
                       tr.outcome_direction AS outcome_direction, count(*) AS n
            """, sid=sid)] if cids else []

            # 相关评估
            assessments = [dict(r) for r in s.run("""
                MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(x)
                WHERE (x:EngineeringStrategy AND x.strategy_id = $sid)
                   OR (x:EngineeredPhageConstruct AND x.construct_id IN $cids)
                RETURN ta.evidence_maturity AS em, ta.safety_uncertainty AS su,
                       ta.manufacturability_risk AS mr, ta.internal_capability_gap AS icg
            """, sid=sid, cids=cids)] if cids else []

            em_list = [a["em"] for a in assessments if a.get("em")]
            if base.get("em"):
                em_list.append(base["em"])

            # 相关组织
            orgs = sorted({
                r["o"] for r in s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)<-[:DEVELOPS]-(o:Organization)
                    RETURN DISTINCT o.canonical_name AS o
                """, sid=sid)
            })

            # 相关专利
            patents = [dict(r) for r in s.run("""
                MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)-[:COVERED_BY]->(pf:PatentFamily)
                RETURN DISTINCT pf.patent_family_id AS pid, pf.title AS title,
                       pf.legal_status AS status
            """, sid=sid)]

            strategies.append({
                "strategy_id": base["sid"], "strategy_type": base["stype"],
                "description": base.get("desc"),
                "intended_capabilities": capabilities,
                "reported_results": results,
                "evidence_maturity": _max_maturity(em_list),
                "safety_uncertainties": _collect_levels(assessments, "su"),
                "manufacturing_considerations": _collect_levels(assessments, "mr"),
                "internal_capability_gaps": _collect_levels(assessments, "icg"),
                "known_organizations": orgs,
                "associated_patents": patents,
                "construct_count": len(constructs),
            })

    return {
        "as_of_date": _today(),
        "strategies": strategies,
        "comparison_matrix": _build_strategy_matrix(strategies),
    }


def _collect_levels(assessments, field):
    """从评估列表中提取指定字段的非 unknown 值。"""
    out = []
    for a in assessments:
        v = a.get(field)
        if v and v != "unknown":
            out.append({"level": v})
    return out


def _build_strategy_matrix(strategies):
    """构建策略对比矩阵（每种策略一行）。"""
    return {
        "strategy_types": [s["strategy_type"] for s in strategies],
        "construct_count": [s["construct_count"] for s in strategies],
        "evidence_maturity": [s["evidence_maturity"] for s in strategies],
        "organization_count": [len(s["known_organizations"]) for s in strategies],
        "patent_count": [len(s["associated_patents"]) for s in strategies],
    }


def identify_landscape_white_space(driver, pathogen_scope=None,
                                   indication_scope=None, technology_scope=None):
    """
    识别格局白空间。

    枚举 strategy × pathogen 组合，统计每个组合的：
        - construct_count（构建体数量）
        - evidence_density（技术结果数量）
        - patent_density（专利数量）
        - known_competitor_count（组织数量）

    根据 construct_count 判定 coverage：
        0     → empty
        1     → minimal
        2-3   → sparse
        >=4   → covered

    Args:
        pathogen_scope: 病原物种列表（可选，空则取前 30）
        indication_scope: 适应症范围（预留）
        technology_scope: 工程策略类型列表（可选，空则取前 30）

    Returns:
        Dict: {underrepresented_combinations, summary, disclaimer, ...}
    """
    pathogen_scope = pathogen_scope or []
    indication_scope = indication_scope or []
    technology_scope = technology_scope or []

    with driver.session() as s:
        # 确定病原范围
        if pathogen_scope:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen) WHERE p.species IN $sp
                RETURN p.pathogen_id AS pid, p.species AS species
            """, sp=pathogen_scope)]
        else:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen) RETURN p.pathogen_id AS pid, p.species AS species LIMIT 30
            """)]
        # 确定策略范围
        if technology_scope:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy) WHERE es.strategy_type IN $st
                RETURN es.strategy_id AS sid, es.strategy_type AS stype
            """, st=technology_scope)]
        else:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy)
                RETURN es.strategy_id AS sid, es.strategy_type AS stype LIMIT 30
            """)]

        combos = []
        for st in strategies:
            for pa in pathogens:
                # 统计构建体数量
                cc = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    RETURN count(DISTINCT ec) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]
                # 统计证据密度
                ec = s.run("""
                    MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
                          -[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    RETURN count(DISTINCT tr) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]
                # 统计专利密度
                pc = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)-[:COVERED_BY]->(pf:PatentFamily)
                    RETURN count(DISTINCT pf) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]
                # 统计组织数
                oc = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)<-[:DEVELOPS]-(o:Organization)
                    RETURN count(DISTINCT o) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]

                # 根据构建体数量判定覆盖等级
                if cc == 0:
                    coverage = "empty"
                elif cc == 1:
                    coverage = "minimal"
                elif cc <= 3:
                    coverage = "sparse"
                else:
                    coverage = "covered"
                combos.append({
                    "strategy_type": st["stype"], "pathogen_species": pa["species"],
                    "construct_count": cc, "evidence_density": ec,
                    "patent_density": pc, "known_competitor_count": oc,
                    "coverage": coverage,
                    "data_quality": "ok" if cc > 0 else "insufficient",
                })

    underrepresented = [c for c in combos if c["coverage"] in ("empty", "minimal", "sparse")]
    underrepresented.sort(key=lambda x: (x["construct_count"], -x["evidence_density"]))
    return {
        "as_of_date": _today(),
        "filters": {"pathogen_scope": pathogen_scope,
                    "indication_scope": indication_scope,
                    "technology_scope": technology_scope},
        "underrepresented_combinations": underrepresented,
        "summary": {
            "total_combinations": len(combos),
            "underrepresented_count": len(underrepresented),
            "empty_count": sum(1 for c in combos if c["coverage"] == "empty"),
            "minimal_count": sum(1 for c in combos if c["coverage"] == "minimal"),
            "sparse_count": sum(1 for c in combos if c["coverage"] == "sparse"),
            "covered_count": sum(1 for c in combos if c["coverage"] == "covered"),
        },
        "disclaimer": WHITE_SPACE_DISCLAIMER,
    }


# ==================================================================
# Part 4: PatentFamily (原 patent_service.py)
# ==================================================================

LEGAL_STATUSES = {"pending", "granted", "expired", "abandoned", "unknown"}


def generate_patent_family_id() -> str:
    """生成专利族 ID（格式：CI:PATENT:XXXXXXXX）。"""
    return f"CI:PATENT:{uuid.uuid4().hex[:8].upper()}"


def create_patent_family(
    driver, title, priority_date=None, application_numbers=None,
    publication_numbers=None, jurisdictions=None, applicants=None,
    assignees=None, legal_status="unknown", claim_scope_summary=None,
    source_url=None, organization_id=None, program_ids=None, actor_id="system",
):
    """
    创建专利族。

    - 幂等检查：若 priority_date + publication_numbers 命中已有专利族，返回已有 ID
    - 建立 OWNS_PATENT 关系（组织）
    - 建立 COVERED_BY 关系（项目）
    """
    if legal_status not in LEGAL_STATUSES:
        raise ValueError(f"legal_status 必须是 {LEGAL_STATUSES} 之一")

    application_numbers = application_numbers or []
    publication_numbers = publication_numbers or []
    jurisdictions = jurisdictions or []
    applicants = applicants or []
    assignees = assignees or []
    program_ids = program_ids or []

    patent_family_id = generate_patent_family_id()

    with driver.session() as session:
        # 幂等检查
        if priority_date and publication_numbers:
            existing = session.run("""
                MATCH (pf:PatentFamily)
                WHERE pf.priority_date = $pd
                  AND ANY(pub IN $pubs WHERE pub IN pf.publication_numbers)
                RETURN pf.patent_family_id AS id LIMIT 1
            """, pd=priority_date, pubs=publication_numbers).single()
            if existing:
                print(f"ℹ️ 疑似重复专利族，已存在: {existing['id']}")
                return existing["id"]

        # 创建节点
        session.run("""
            CREATE (pf:PatentFamily {
                patent_family_id: $pfid, title: $title,
                priority_date: $priority_date,
                application_numbers: $application_numbers,
                publication_numbers: $publication_numbers,
                jurisdictions: $jurisdictions, applicants: $applicants,
                assignees: $assignees, legal_status: $legal_status,
                claim_scope_summary: $claim_scope_summary,
                source_url: $source_url, review_status: 'pending',
                last_verified_at: datetime(),
                created_at: datetime(), updated_at: datetime()
            })
        """, pfid=patent_family_id, title=title, priority_date=priority_date,
             application_numbers=application_numbers,
             publication_numbers=publication_numbers,
             jurisdictions=jurisdictions, applicants=applicants,
             assignees=assignees, legal_status=legal_status,
             claim_scope_summary=claim_scope_summary, source_url=source_url)

        # 关联组织
        if organization_id:
            session.run("""
                MATCH (o:Organization {organization_id: $oid})
                MATCH (pf:PatentFamily {patent_family_id: $pfid})
                MERGE (o)-[:OWNS_PATENT]->(pf)
            """, oid=organization_id, pfid=patent_family_id)

        # 关联项目
        for pid in program_ids:
            session.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MATCH (pf:PatentFamily {patent_family_id: $pfid})
                MERGE (d)-[:COVERED_BY]->(pf)
            """, pid=pid, pfid=patent_family_id)

        write_audit_event(
            driver, action_type="CREATE",
            object_type="PatentFamily", object_id=patent_family_id,
            actor_id=actor_id,
            delta={"title": title, "legal_status": legal_status,
                   "publication_numbers": publication_numbers,
                   "organization_id": organization_id},
            reason=f"创建专利族: {title[:60]}",
        )
    return patent_family_id


def get_patent_family(driver, patent_family_id):
    """按 ID 查询专利族，附带所有者和关联项目。"""
    with driver.session() as session:
        r = session.run("""
            MATCH (pf:PatentFamily {patent_family_id: $pfid})
            OPTIONAL MATCH (o:Organization)-[:OWNS_PATENT]->(pf)
            OPTIONAL MATCH (d:DevelopmentProgram)-[:COVERED_BY]->(pf)
            RETURN pf,
                   collect(DISTINCT o.canonical_name) AS owners,
                   collect(DISTINCT d.canonical_name) AS programs
        """, pfid=patent_family_id).single()
        if not r:
            return None
        data = dict(r["pf"])
        data["owners"] = r["owners"]
        data["programs"] = r["programs"]
        return data


def list_patent_families_for_program(driver, program_id):
    """列出某项目覆盖的所有专利族。"""
    with driver.session() as session:
        r = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})-[:COVERED_BY]->(pf:PatentFamily)
            OPTIONAL MATCH (o:Organization)-[:OWNS_PATENT]->(pf)
            RETURN pf.patent_family_id AS id, pf.title AS title,
                   pf.legal_status AS legal_status,
                   pf.priority_date AS priority_date,
                   pf.jurisdictions AS jurisdictions,
                   collect(DISTINCT o.canonical_name) AS owners
            ORDER BY pf.priority_date DESC
        """, pid=program_id)
        return [dict(rec) for rec in r]


def list_patent_families_for_organization(driver, organization_id):
    """列出某组织拥有的所有专利族。"""
    with driver.session() as session:
        r = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:OWNS_PATENT]->(pf:PatentFamily)
            RETURN pf.patent_family_id AS id, pf.title AS title,
                   pf.legal_status AS legal_status,
                   pf.priority_date AS priority_date,
                   pf.publication_numbers AS publication_numbers
            ORDER BY pf.priority_date DESC
        """, oid=organization_id)
        return [dict(rec) for rec in r]