# src/engineering_intelligence/technology_brief.py
"""
工程化噬菌体技术简报（Technology Brief）生成器
符合 PRD 16.2 的 JSON 结构 + EPI-07 功能验收

核心原则：
- 只从图谱中已存在的对象组织内容，不调用 LLM 生成事实
- 主张（Claim）与结果（Result）严格分离
- 技术成熟度不得高于已审核证据支持的最高阶段（在建议下一步中体现）
- 所有关键事实必须绑定 SourceArtifact
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from neo4j import Driver

from src.ci.intelligence_product_service import create_intelligence_product


# ============================================================
# 成熟度与风险等级
# ============================================================

MATURITY_ORDER = {
    "conceptual": 0,
    "in_vitro": 1,
    "in_vivo": 2,
    "clinical": 3,
}

RISK_LEVELS = {"high", "medium", "low", "unknown"}


def _max_maturity(levels: List[str]) -> str:
    """返回给定成熟度列表中的最高级别"""
    if not levels:
        return "conceptual"
    return max(levels, key=lambda x: MATURITY_ORDER.get(x, 0))


# ============================================================
# 主入口
# ============================================================

def generate_technology_brief(
    driver: Driver,
    strategy_id: Optional[str] = None,
    construct_id: Optional[str] = None,
    pathogen_id: Optional[str] = None,
    as_of_date: Optional[str] = None,
    technology_question: str = "",
    persist: bool = True,
    actor_id: str = "system",
) -> Dict:
    """
    生成工程化噬菌体技术简报。

    参数：
        strategy_id / construct_id / pathogen_id：至少提供其一
        as_of_date：信息截止日期，默认今天
        technology_question：本条简报要回答的技术情报问题（可选）
        persist：True 时落库为 IntelligenceProduct 节点

    返回：
        Dict，符合 PRD 16.2 的结构，并附带 brief_id（若 persist=True）
    """
    if not (strategy_id or construct_id or pathogen_id):
        raise ValueError(
            "至少需要提供 strategy_id / construct_id / pathogen_id 之一"
        )

    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")

    # ---------- 1. 抓取图谱数据 ----------
    strategies = _fetch_strategies(driver, strategy_id, construct_id, pathogen_id)
    constructs = _fetch_constructs(driver, strategy_id, construct_id, pathogen_id)
    pathogens = _fetch_target_pathogens(driver, strategy_id, construct_id, pathogen_id)

    construct_ids = [c["construct_id"] for c in constructs]
    claims = _fetch_technical_claims(driver, construct_ids)
    results = _fetch_technical_results(driver, construct_ids)
    assessments = _fetch_technology_assessments(driver, strategy_id, construct_id)
    citations = _fetch_citations(driver, construct_ids)
    patent_families = _fetch_patent_families(driver, strategy_id, construct_id, pathogen_id)

    # ---------- 2. 聚合分析 ----------
    evidence_maturity = _aggregate_evidence_maturity(assessments, constructs)
    safety_uncertainties = _aggregate_risk_field(
        assessments, field="safety_uncertainty", label="安全性"
    )
    manufacturing_uncertainties = _aggregate_risk_field(
        assessments, field="manufacturability_risk", label="可制造性"
    )
    internal_capability_gaps = _aggregate_capability_gaps(assessments)
    recommended_next_steps = _build_recommended_next_steps(
        constructs, claims, results, assessments, evidence_maturity
    )
    executive_summary = _build_executive_summary(
        strategies, constructs, pathogens, claims, results, assessments
    )
    data_gaps = _collect_data_gaps(constructs, claims, results, patent_families)

    # ---------- 3. 组装简报 ----------
    brief_data: Dict = {
        "brief_type": "engineered_phage_technology",
        "as_of_date": as_of_date,
        "generated_at": datetime.now().isoformat(),
        "technology_question": technology_question,
        "engineering_strategies": strategies,
        "known_constructs": constructs,
        "target_pathogens": pathogens,
        "technical_claims": claims,
        "technical_results": results,
        "evidence_maturity": evidence_maturity,
        "patent_families": patent_families,
        "safety_uncertainties": safety_uncertainties,
        "manufacturing_uncertainties": manufacturing_uncertainties,
        "internal_capability_gaps": internal_capability_gaps,
        "recommended_next_steps": recommended_next_steps,
        "citations": citations,
        "review_status": "pending",
    }

    # ---------- 4. 持久化 ----------
    if persist:
        title = _build_brief_title(strategies, constructs, pathogens)
        brief_id = create_intelligence_product(
            driver,
            brief_type="engineered_phage_technology",
            title=title,
            executive_summary=executive_summary,
            organization_id=None,          # 技术简报不绑定单一组织
            as_of_date=as_of_date,
            citations=citations,
            competitive_assessment={},     # 技术简报暂不填竞争者视角
            data_gaps=data_gaps,
            recommended_next_steps=recommended_next_steps,
            actor_id=actor_id,
        )
        brief_data["brief_id"] = brief_id
        _link_brief_to_subjects(
            driver, brief_id,
            strategy_ids=[s["strategy_id"] for s in strategies],
            construct_ids=construct_ids,
            pathogen_ids=[p["pathogen_id"] for p in pathogens],
        )
    else:
        brief_data["brief_id"] = None

    return brief_data


# ============================================================
# 数据抓取
# ============================================================

def _fetch_strategies(
    driver: Driver,
    strategy_id: Optional[str],
    construct_id: Optional[str],
    pathogen_id: Optional[str],
) -> List[Dict]:
    filters = []
    params: Dict = {}
    if strategy_id:
        filters.append("es.strategy_id = $sid")
        params["sid"] = strategy_id
    if construct_id:
        filters.append(
            "EXISTS { MATCH (:EngineeredPhageConstruct {construct_id: $cid})-[:IMPLEMENTS]->(es) }"
        )
        params["cid"] = construct_id
    if pathogen_id:
        filters.append(
            "EXISTS { MATCH (:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es) "
            "MATCH (:EngineeredPhageConstruct)-[:TARGETS]->(:Pathogen {pathogen_id: $pid}) }"
        )
        params["pid"] = pathogen_id
    where_clause = " AND ".join(filters) if filters else "true"

    query = f"""
        MATCH (es:EngineeringStrategy)
        WHERE {where_clause}
        OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es)
        WITH es, count(DISTINCT ec) AS construct_count
        RETURN es.strategy_id AS strategy_id,
               es.strategy_type AS strategy_type,
               es.description AS description,
               es.evidence_maturity AS evidence_maturity,
               es.review_status AS review_status,
               construct_count
        ORDER BY strategy_type
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _fetch_constructs(
    driver: Driver,
    strategy_id: Optional[str],
    construct_id: Optional[str],
    pathogen_id: Optional[str],
) -> List[Dict]:
    filters = []
    params: Dict = {}
    if construct_id:
        filters.append("ec.construct_id = $cid")
        params["cid"] = construct_id
    if strategy_id:
        filters.append(
            "EXISTS { MATCH (ec)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid}) }"
        )
        params["sid"] = strategy_id
    if pathogen_id:
        filters.append(
            "EXISTS { MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid}) }"
        )
        params["pid"] = pathogen_id
    where_clause = " AND ".join(filters) if filters else "true"

    query = f"""
        MATCH (ec:EngineeredPhageConstruct)
        WHERE {where_clause}
        OPTIONAL MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
        OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
        OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
        OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(dp:DevelopmentProgram)
        WITH ec,
             collect(DISTINCT es.strategy_type) AS strategy_types,
             collect(DISTINCT p.species) AS target_pathogens,
             collect(DISTINCT dp.canonical_name) AS programs,
             collect(DISTINCT ph.name) AS parent_phages
        RETURN ec.construct_id AS construct_id,
               ec.public_name AS public_name,
               ec.construct_code AS construct_code,
               ec.construct_status AS construct_status,
               ec.intended_effects AS intended_effects,
               ec.first_public_date AS first_public_date,
               ec.review_status AS review_status,
               strategy_types,
               target_pathogens,
               parent_phages[0] AS parent_phage,
               programs,
               ec.created_at AS created_at
        ORDER BY created_at DESC
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _fetch_target_pathogens(
    driver: Driver,
    strategy_id: Optional[str],
    construct_id: Optional[str],
    pathogen_id: Optional[str],
) -> List[Dict]:
    filters = []
    params: Dict = {}
    if pathogen_id:
        filters.append("p.pathogen_id = $pid")
        params["pid"] = pathogen_id
    if construct_id:
        filters.append(
            "EXISTS { MATCH (:EngineeredPhageConstruct {construct_id: $cid})-[:TARGETS]->(p) }"
        )
        params["cid"] = construct_id
    if strategy_id:
        filters.append(
            "EXISTS { MATCH (:EngineeredPhageConstruct)-[:IMPLEMENTS]->"
            "(:EngineeringStrategy {strategy_id: $sid}) "
            "MATCH (:EngineeredPhageConstruct)-[:TARGETS]->(p) }"
        )
        params["sid"] = strategy_id
    where_clause = " AND ".join(filters) if filters else "true"

    query = f"""
        MATCH (p:Pathogen)
        WHERE {where_clause}
        OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:TARGETS]->(p)
        WITH p, count(DISTINCT ec) AS construct_count
        RETURN p.pathogen_id AS pathogen_id,
               p.species AS species,
               p.resistance_mechanism AS resistance_mechanism,
               construct_count
        ORDER BY construct_count DESC, species
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _fetch_technical_claims(driver: Driver, construct_ids: List[str]) -> List[Dict]:
    if not construct_ids:
        return []
    query = """
        MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec:EngineeredPhageConstruct)
        WHERE ec.construct_id IN $cids
        OPTIONAL MATCH (tc)-[:SUPPORTED_BY]->(s:SourceArtifact)
        WITH tc, ec, collect(DISTINCT s.source_id) AS source_ids
        RETURN tc.claim_id AS claim_id,
               tc.claim_type AS claim_type,
               tc.claim_text AS claim_text,
               tc.claimant_type AS claimant_type,
               tc.evidence_context AS evidence_context,
               tc.claim_status AS claim_status,
               tc.confidence AS confidence,
               ec.construct_id AS construct_id,
               ec.public_name AS construct_name,
               source_ids
        ORDER BY tc.created_at DESC
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, cids=construct_ids)]


def _fetch_technical_results(driver: Driver, construct_ids: List[str]) -> List[Dict]:
    if not construct_ids:
        return []
    query = """
        MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
        WHERE ec.construct_id IN $cids
        OPTIONAL MATCH (tr)-[:REPORTED_IN]->(s:SourceArtifact)
        WITH tr, ec, collect(DISTINCT s.source_id) AS source_ids
        RETURN tr.result_id AS result_id,
               tr.result_type AS result_type,
               tr.study_context AS study_context,
               tr.outcome_direction AS outcome_direction,
               tr.metric_name AS metric_name,
               tr.metric_value AS metric_value,
               tr.metric_unit AS metric_unit,
               tr.sample_size AS sample_size,
               tr.limitation_summary AS limitation_summary,
               tr.reproducibility_status AS reproducibility_status,
               ec.construct_id AS construct_id,
               ec.public_name AS construct_name,
               source_ids
        ORDER BY tr.created_at DESC
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, cids=construct_ids)]


def _fetch_technology_assessments(
    driver: Driver,
    strategy_id: Optional[str],
    construct_id: Optional[str],
) -> List[Dict]:
    """
    抓取技术评估（★ 双向抓取）：
      - 若给 strategy_id：抓「该策略本身的评估」+「该策略下所有构建体的评估」
      - 若给 construct_id：抓「该构建体本身的评估」+「其所属策略的评估」
      - 两个都给：抓全部相关评估（并集）
    """
    conditions = []
    params: Dict = {}

    if strategy_id:
        # ① 策略本身的评估
        conditions.append(
            "(ta.subject_type = 'strategy' AND ta.subject_id = $sid)"
        )
        # ② 该策略下所有构建体的评估
        conditions.append(
            """
            (ta.subject_type = 'construct' AND EXISTS {
                MATCH (ec:EngineeredPhageConstruct {construct_id: ta.subject_id})
                      -[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
            })
            """
        )
        params["sid"] = strategy_id

    if construct_id:
        # ③ 构建体本身的评估
        conditions.append(
            "(ta.subject_type = 'construct' AND ta.subject_id = $cid)"
        )
        # ④ 其所属策略的评估
        conditions.append(
            """
            (ta.subject_type = 'strategy' AND EXISTS {
                MATCH (:EngineeredPhageConstruct {construct_id: $cid})
                      -[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: ta.subject_id})
            })
            """
        )
        params["cid"] = construct_id

    where_clause = " OR ".join(conditions) if conditions else "true"

    query = f"""
        MATCH (ta:TechnologyAssessment)
        WHERE {where_clause}
        RETURN ta.technology_assessment_id AS assessment_id,
               ta.subject_type AS subject_type,
               ta.subject_id AS subject_id,
               ta.evidence_maturity AS evidence_maturity,
               ta.technical_relevance AS technical_relevance,
               ta.translational_potential AS translational_potential,
               ta.manufacturability_risk AS manufacturability_risk,
               ta.safety_uncertainty AS safety_uncertainty,
               ta.ip_relevance AS ip_relevance,
               ta.internal_capability_gap AS internal_capability_gap,
               ta.assessment_summary AS summary,
               ta.review_status AS review_status
        ORDER BY ta.created_at DESC
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def _fetch_citations(driver: Driver, construct_ids: List[str]) -> List[Dict]:
    """抓取与构建体相关的技术主张 / 结果背后的 SourceArtifact"""
    if not construct_ids:
        return []
    query = """
        MATCH (ec:EngineeredPhageConstruct)
        WHERE ec.construct_id IN $cids
        OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
        OPTIONAL MATCH (tc)-[:SUPPORTED_BY]->(s1:SourceArtifact)
        OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
        OPTIONAL MATCH (tr)-[:REPORTED_IN]->(s2:SourceArtifact)
        WITH collect(DISTINCT s1) + collect(DISTINCT s2) AS sources
        UNWIND sources AS s
        WITH DISTINCT s
        WHERE s IS NOT NULL
        RETURN s.source_id AS source_id,
               s.source_type AS source_type,
               s.title AS title,
               s.url AS url,
               s.published_date AS published_date,
               s.credibility_tier AS credibility_tier
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, cids=construct_ids)]


def _fetch_patent_families(
    driver: Driver,
    strategy_id: Optional[str],
    construct_id: Optional[str],
    pathogen_id: Optional[str],
) -> List[Dict]:
    """
    抓取与策略/构建体/病原相关的专利族：
    - 若给了 construct_id → 通过 (construct)-[:ASSOCIATED_WITH]->(program) 找 program
    - 若给了 strategy_id → 通过 (construct)-[:IMPLEMENTS]->(strategy) 找 construct，再找 program
    - 若给了 pathogen_id → 通过 (construct)-[:TARGETS]->(pathogen) 找 construct，再找 program
    - 最终通过 (program)-[:COVERED_BY]->(PatentFamily) 抓取
    """
    filters = []
    params: Dict = {}
    if construct_id:
        filters.append("ec.construct_id = $cid")
        params["cid"] = construct_id
    if strategy_id:
        filters.append(
            "EXISTS { MATCH (ec)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid}) }"
        )
        params["sid"] = strategy_id
    if pathogen_id:
        filters.append(
            "EXISTS { MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid}) }"
        )
        params["pid"] = pathogen_id
    if not filters:
        return []
    where_clause = " AND ".join(filters)

    query = f"""
        MATCH (ec:EngineeredPhageConstruct)
        WHERE {where_clause}
        OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(dp:DevelopmentProgram)
        OPTIONAL MATCH (dp)-[:COVERED_BY]->(pf:PatentFamily)
        WITH pf
        WHERE pf IS NOT NULL
        OPTIONAL MATCH (o:Organization)-[:OWNS_PATENT]->(pf)
        WITH pf, collect(DISTINCT o.canonical_name) AS owners
        RETURN pf.patent_family_id AS patent_family_id,
               pf.title AS title,
               pf.legal_status AS legal_status,
               pf.priority_date AS priority_date,
               pf.jurisdictions AS jurisdictions,
               pf.publication_numbers AS publication_numbers,
               pf.claim_scope_summary AS claim_scope_summary,
               owners
        ORDER BY pf.priority_date DESC
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


# ============================================================
# 聚合与建议
# ============================================================

def _aggregate_evidence_maturity(
    assessments: List[Dict],
    constructs: List[Dict],
) -> Dict:
    by_construct = []
    by_strategy = []
    distribution = {"conceptual": 0, "in_vitro": 0, "in_vivo": 0, "clinical": 0}

    cid_maturity = {}
    sid_maturity = {}
    for a in assessments:
        m = a.get("evidence_maturity") or "conceptual"
        if a.get("subject_type") == "construct":
            cid_maturity[a["subject_id"]] = m
        elif a.get("subject_type") == "strategy":
            sid_maturity[a["subject_id"]] = m

    # ★ 警告：如果构建体存在但拿不到构建体级评估，说明查询可能漏了
    if constructs and not cid_maturity:
        print(
            f"⚠️ 警告：{len(constructs)} 个构建体存在，但未找到对应的构建体级评估。"
            f"请检查 _fetch_technology_assessments 是否正确抓到构建体评估。"
        )

    for c in constructs:
        m = cid_maturity.get(c["construct_id"], "conceptual")
        by_construct.append({
            "construct_id": c["construct_id"],
            "name": c.get("public_name"),
            "maturity": m,
        })
        if m in distribution:
            distribution[m] += 1

    for sid, m in sid_maturity.items():
        by_strategy.append({"strategy_id": sid, "maturity": m})

    # highest_maturity 同时考虑策略级和构建体级
    all_maturities = list(cid_maturity.values()) + list(sid_maturity.values())
    return {
        "by_construct": by_construct,
        "by_strategy": by_strategy,
        "distribution": distribution,
        "highest_maturity": _max_maturity(all_maturities),
    }


def _aggregate_risk_field(
    assessments: List[Dict],
    field: str,
    label: str,
) -> List[Dict]:
    items = []
    for a in assessments:
        v = a.get(field)
        if v and v != "unknown":
            items.append({
                "subject_type": a.get("subject_type"),
                "subject_id": a.get("subject_id"),
                "level": v,
                "label": label,
                "summary": a.get("summary"),
            })
    return items


def _aggregate_capability_gaps(assessments: List[Dict]) -> List[Dict]:
    gaps = []
    for a in assessments:
        v = a.get("internal_capability_gap")
        if v in ("high", "medium"):
            gaps.append({
                "subject_type": a.get("subject_type"),
                "subject_id": a.get("subject_id"),
                "gap_level": v,
                "summary": a.get("summary"),
            })
    return gaps


def _build_recommended_next_steps(
    constructs: List[Dict],
    claims: List[Dict],
    results: List[Dict],
    assessments: List[Dict],
    evidence_maturity: Dict,
) -> List[str]:
    steps: List[str] = []

    if not assessments:
        steps.append("尚未生成技术评估，建议由领域专家补充评估后再做决策。")

    if claims and not results:
        steps.append("存在技术主张但缺少实验/研究结果，建议补充体外或体内数据验证。")

    distribution = evidence_maturity.get("distribution", {})
    if distribution.get("clinical", 0) == 0 and distribution.get("in_vivo", 0) == 0:
        steps.append("当前证据成熟度均停留在体外阶段，临床转化存在明显不确定性。")

    if any(a.get("internal_capability_gap") == "high" for a in assessments):
        steps.append("内部能力差距被评为 high，建议评估合作/引进/自建三条路径。")

    if any(
        (a.get("safety_uncertainty") or "") == "high"
        or (a.get("manufacturability_risk") or "") == "high"
        for a in assessments
    ):
        steps.append("安全性或可制造性风险高，建议在立项前完成风险专项评估。")

    if not steps:
        steps.append("建议持续观察该方向的公开证据更新，并每季度复核一次。")

    return steps


def _build_executive_summary(
    strategies: List[Dict],
    constructs: List[Dict],
    pathogens: List[Dict],
    claims: List[Dict],
    results: List[Dict],
    assessments: List[Dict],
) -> str:
    s_count = len(strategies)
    c_count = len(constructs)
    p_count = len(pathogens)
    cl_count = len(claims)
    r_count = len(results)
    a_count = len(assessments)

    strategy_types = ", ".join(
        sorted({s.get("strategy_type", "") for s in strategies if s.get("strategy_type")})
    ) or "未指定策略"

    species = ", ".join(
        sorted({p.get("species", "") for p in pathogens if p.get("species")})
    ) or "未指定病原"

    return (
        f"本简报围绕 {strategy_types} 策略，覆盖 {c_count} 个公开构建体、"
        f"{p_count} 个目标病原（{species}）。"
        f"共收集 {cl_count} 条技术主张、{r_count} 条技术结果、"
        f"{a_count} 份技术评估。"
        f"主张与结果已分离存储，所有关键事实均已回溯至来源对象。"
    )


def _collect_data_gaps(
    constructs: List[Dict],
    claims: List[Dict],
    results: List[Dict],
    patent_families: Optional[List[Dict]] = None,
) -> List[str]:
    gaps: List[str] = []
    if not constructs:
        gaps.append("尚无公开工程构建体入库")
    if not claims:
        gaps.append("尚无技术主张入库")
    if not results:
        gaps.append("尚无技术结果入库")
    for c in constructs:
        if not c.get("strategy_types"):
            gaps.append(f"构建体 {c.get('public_name') or c.get('construct_id')} 未关联任何工程策略")
        if not c.get("target_pathogens"):
            gaps.append(f"构建体 {c.get('public_name') or c.get('construct_id')} 未关联目标病原")
    # 专利族缺失仅作为提示，不阻塞简报生成（Stage2B 范围）
    if not (patent_families or []):
        gaps.append("尚未关联任何专利族（PatentFamily）")
    return gaps


def _build_brief_title(
    strategies: List[Dict],
    constructs: List[Dict],
    pathogens: List[Dict],
) -> str:
    if len(strategies) == 1 and strategies[0].get("strategy_type"):
        subject = strategies[0]["strategy_type"]
    elif len(constructs) == 1 and constructs[0].get("public_name"):
        subject = constructs[0]["public_name"]
    elif len(pathogens) == 1 and pathogens[0].get("species"):
        subject = pathogens[0]["species"]
    else:
        subject = "工程化噬菌体技术"
    return f"技术情报简报 - {subject}"


def _link_brief_to_subjects(
    driver: Driver,
    brief_id: str,
    strategy_ids: List[str],
    construct_ids: List[str],
    pathogen_ids: List[str],
) -> None:
    """
    建立 (IntelligenceProduct)-[:COVERS]->(...) 关系。
    与 create_intelligence_product 已建的 Organization COVERS 关系并存。
    """
    with driver.session() as session:
        if strategy_ids:
            session.run(
                """
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                UNWIND $sids AS sid
                MATCH (es:EngineeringStrategy {strategy_id: sid})
                MERGE (b)-[:COVERS]->(es)
                """,
                bid=brief_id, sids=strategy_ids,
            )
        if construct_ids:
            session.run(
                """
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                UNWIND $cids AS cid
                MATCH (ec:EngineeredPhageConstruct {construct_id: cid})
                MERGE (b)-[:COVERS]->(ec)
                """,
                bid=brief_id, cids=construct_ids,
            )
        if pathogen_ids:
            session.run(
                """
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                UNWIND $pids AS pid
                MATCH (p:Pathogen {pathogen_id: pid})
                MERGE (b)-[:COVERS]->(p)
                """,
                bid=brief_id, pids=pathogen_ids,
            )