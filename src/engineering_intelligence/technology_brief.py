# src/engineering_intelligence/technology_brief.py
"""
工程化噬菌体技术简报（Technology Brief）生成器
符合 PRD 16.2 的 JSON 结构 + EPI-07 功能验收

核心原则：
- 只从图谱中已存在的对象组织内容，不调用 LLM 生成事实
- 主张（Claim）与结果（Result）严格分离
- 只纳入 review_status='approved' 的 Claim / Result
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from neo4j import Driver

from src.ci.intelligence_product_service import create_intelligence_product


MATURITY_ORDER = {"conceptual": 0, "in_vitro": 1, "in_vivo": 2, "clinical": 3}
RISK_LEVELS = {"high", "medium", "low", "unknown"}


def _max_maturity(levels):
    if not levels:
        return "conceptual"
    return max(levels, key=lambda x: MATURITY_ORDER.get(x, 0))


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
    if not (strategy_id or construct_id or pathogen_id):
        raise ValueError("至少需要提供 strategy_id / construct_id / pathogen_id 之一")
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")

    strategies = _fetch_strategies(driver, strategy_id, construct_id, pathogen_id)
    constructs = _fetch_constructs(driver, strategy_id, construct_id, pathogen_id)
    pathogens = _fetch_target_pathogens(driver, strategy_id, construct_id, pathogen_id)

    construct_ids = [c["construct_id"] for c in constructs]
    claims = _fetch_technical_claims(driver, construct_ids)
    results = _fetch_technical_results(driver, construct_ids)
    assessments = _fetch_technology_assessments(driver, strategy_id, construct_id)
    citations = _fetch_citations(driver, construct_ids)
    patent_families = _fetch_patent_families(driver, strategy_id, construct_id, pathogen_id)

    evidence_maturity = _aggregate_evidence_maturity(assessments, constructs)
    safety_uncertainties = _aggregate_risk_field(assessments, "safety_uncertainty", "安全性")
    manufacturing_uncertainties = _aggregate_risk_field(assessments, "manufacturability_risk", "可制造性")
    internal_capability_gaps = _aggregate_capability_gaps(assessments)
    recommended_next_steps = _build_recommended_next_steps(
        constructs, claims, results, assessments, evidence_maturity)
    executive_summary = _build_executive_summary(
        strategies, constructs, pathogens, claims, results, assessments)
    data_gaps = _collect_data_gaps(constructs, claims, results, patent_families)

    strategy_comparison = _build_strategy_comparison_block(driver, strategies)
    white_space_analysis = _build_white_space_block(driver, strategies, pathogens)

    # ★ 新增：三个质量能力区块
    source_credibility = _build_source_credibility_block(citations)
    conflict_warnings = _build_conflict_warnings(driver, construct_ids)
    related_patent_mappings = _build_related_patent_mappings(driver, patent_families)

    if strategy_comparison.get("focus_strategy_ids"):
        recommended_next_steps.append(
            f"本简报涉及 {len(strategy_comparison['focus_strategy_ids'])} 个策略，已附同类策略横向对比矩阵")

    ws_summary = white_space_analysis.get("summary", {})
    if isinstance(ws_summary, dict) and ws_summary.get("empty_count", 0) > 0:
        recommended_next_steps.append(
            f"范围内识别到 {ws_summary['empty_count']} 个 empty white-space 组合，建议评估进入策略")

    # ★ 新增：质量能力相关建议
    if source_credibility.get("by_tier", {}).get("tertiary", 0) > 0:
        recommended_next_steps.append(
            f"引用来源中有 {source_credibility['by_tier']['tertiary']} 条三手来源，建议人工核验")
    if conflict_warnings.get("total_conflicts", 0) > 0:
        recommended_next_steps.append(
            f"检测到 {conflict_warnings['total_conflicts']} 条技术冲突，建议领域专家复核")
    if related_patent_mappings.get("total_mappings", 0) > 0:
        recommended_next_steps.append(
            f"该策略关联 {related_patent_mappings['total_mappings']} 条专利-论文映射，建议 IP 部门评估")

    brief_data = {
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
        "strategy_comparison": strategy_comparison,
        "white_space_analysis": white_space_analysis,
        "source_credibility": source_credibility,               # ★ 新增
        "conflict_warnings": conflict_warnings,                 # ★ 新增
        "related_patent_mappings": related_patent_mappings,     # ★ 新增
        "recommended_next_steps": recommended_next_steps,
        "citations": citations,
        "review_status": "pending",
    }

    if persist:
        title = _build_brief_title(strategies, constructs, pathogens)
        brief_id = create_intelligence_product(
            driver, brief_type="engineered_phage_technology",
            title=title, executive_summary=executive_summary,
            organization_id=None, as_of_date=as_of_date,
            citations=citations, competitive_assessment={},
            data_gaps=data_gaps, recommended_next_steps=recommended_next_steps,
            actor_id=actor_id,
        )
        brief_data["brief_id"] = brief_id
        _link_brief_to_subjects(
            driver, brief_id,
            strategy_ids=[s["strategy_id"] for s in strategies],
            construct_ids=construct_ids,
            pathogen_ids=[p["pathogen_id"] for p in pathogens],
        )
        try:
            with driver.session() as s:
                s.run("""
                    MATCH (b:IntelligenceProduct {brief_id: $bid})
                    SET b.strategy_comparison = $sc,
                        b.white_space_analysis = $ws,
                        b.source_credibility = $src,
                        b.conflict_warnings = $cf,
                        b.related_patent_mappings = $pm,
                        b.updated_at = datetime()
                """, bid=brief_id,
                     sc=json.dumps(strategy_comparison, ensure_ascii=False, default=str),
                     ws=json.dumps(white_space_analysis, ensure_ascii=False, default=str),
                     src=json.dumps(source_credibility, ensure_ascii=False, default=str),
                     cf=json.dumps(conflict_warnings, ensure_ascii=False, default=str),
                     pm=json.dumps(related_patent_mappings, ensure_ascii=False, default=str))
        except Exception as e:
            print(f"⚠️ 写入质量能力字段失败: {e}")
    else:
        brief_data["brief_id"] = None

    return brief_data


# ==================== ★ P1 质量能力：三个新函数 ====================

def _build_source_credibility_block(citations: List[Dict]) -> Dict:
    """基于 citations 统计来源可信度分布"""
    tiers = {"primary": 0, "secondary": 0, "tertiary": 0, "unknown": 0}
    for c in citations:
        t = (c.get("credibility_tier") or "unknown").lower()
        tiers[t] = tiers.get(t, 0) + 1
    return {
        "total_sources": len(citations),
        "by_tier": tiers,
        "note": "来源可信度只反映渠道可靠性，不代表内容正确性。",
    }


def _build_conflict_warnings(driver: Driver, construct_ids: List[str]) -> Dict:
    """扫描构建体下的所有冲突"""
    if not construct_ids:
        return {"total_conflicts": 0, "claim_status_conflicts": [],
                "result_direction_conflicts": [], "note": "无构建体"}
    try:
        from src.engineering_intelligence.claim_conflict_service import detect_conflicts
        all_conflicts = {"claim_status_conflicts": [], "result_direction_conflicts": [],
                         "cross_construct_conflicts": [], "total_conflicts": 0}
        for cid in construct_ids:
            r = detect_conflicts(driver, construct_id=cid, persist=False)
            all_conflicts["claim_status_conflicts"].extend(r.get("claim_status_conflicts", []))
            all_conflicts["result_direction_conflicts"].extend(r.get("result_direction_conflicts", []))
            all_conflicts["total_conflicts"] += r.get("total_conflicts", 0)
        return {
            "total_conflicts": all_conflicts["total_conflicts"],
            "claim_status_conflicts": all_conflicts["claim_status_conflicts"][:5],
            "result_direction_conflicts": all_conflicts["result_direction_conflicts"][:5],
            "note": "冲突检测只标记矛盾的主张/结果，不做真伪判断。",
        }
    except Exception as e:
        return {"total_conflicts": 0, "claim_status_conflicts": [],
                "result_direction_conflicts": [], "error": str(e)}


def _build_related_patent_mappings(driver: Driver, patent_families: List[Dict]) -> Dict:
    """列出专利族与技术主张的映射关系"""
    if not patent_families:
        return {"total_mappings": 0, "mappings": [], "note": "无关联专利族"}
    try:
        from src.engineering_intelligence.ip_mapping_service import list_mappings_for_patent
        all_mappings = []
        for pf in patent_families:
            pfid = pf.get("patent_family_id")
            if not pfid:
                continue
            try:
                mappings = list_mappings_for_patent(driver, pfid)
                for m in mappings:
                    m["patent_family_id"] = pfid
                    m["patent_title"] = pf.get("title")
                all_mappings.extend(mappings)
            except Exception:
                pass
        return {
            "total_mappings": len(all_mappings),
            "mappings": all_mappings[:10],
            "note": "专利-论文映射基于文本相似度，不代表侵权或自由实施判断。",
        }
    except Exception as e:
        return {"total_mappings": 0, "mappings": [], "error": str(e)}


# ==================== 原有辅助函数（保持不变） ====================

def _build_strategy_comparison_block(driver, strategies):
    focus_ids = [s["strategy_id"] for s in strategies if s.get("strategy_id")]
    if not focus_ids:
        return {"strategies": [], "comparison_matrix": {}, "focus_strategy_ids": []}
    try:
        from src.ci.landscape_service import compare_engineering_strategies
        with driver.session() as s:
            all_ids = [r["sid"] for r in s.run("""
                MATCH (es:EngineeringStrategy)
                RETURN es.strategy_id AS sid ORDER BY es.strategy_type LIMIT 10
            """)]
        if not all_ids:
            all_ids = focus_ids
        r = compare_engineering_strategies(driver, all_ids)
        return {"focus_strategy_ids": focus_ids,
                "strategies": r.get("strategies", []),
                "comparison_matrix": r.get("comparison_matrix", {})}
    except Exception as e:
        return {"focus_strategy_ids": focus_ids, "strategies": [],
                "comparison_matrix": {}, "error": str(e)}


def _build_white_space_block(driver, strategies, pathogens):
    pathogen_scope = [p["species"] for p in pathogens if p.get("species")]
    tech_scope = [s["strategy_type"] for s in strategies if s.get("strategy_type")]
    try:
        from src.ci.landscape_service import identify_landscape_white_space
        ws = identify_landscape_white_space(
            driver, pathogen_scope=pathogen_scope or None,
            technology_scope=tech_scope or None)
        return {"pathogen_scope": pathogen_scope, "technology_scope": tech_scope,
                "underrepresented_combinations": ws["underrepresented_combinations"][:10],
                "summary": ws["summary"], "disclaimer": ws["disclaimer"]}
    except Exception as e:
        return {"pathogen_scope": pathogen_scope, "technology_scope": tech_scope,
                "underrepresented_combinations": [], "summary": {},
                "disclaimer": "", "error": str(e)}


def _fetch_strategies(driver, strategy_id, construct_id, pathogen_id):
    filters, params = [], {}
    if strategy_id:
        filters.append("es.strategy_id = $sid"); params["sid"] = strategy_id
    if construct_id:
        filters.append("EXISTS { MATCH (:EngineeredPhageConstruct {construct_id: $cid})-[:IMPLEMENTS]->(es) }")
        params["cid"] = construct_id
    if pathogen_id:
        filters.append("EXISTS { MATCH (:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es) MATCH (:EngineeredPhageConstruct)-[:TARGETS]->(:Pathogen {pathogen_id: $pid}) }")
        params["pid"] = pathogen_id
    where = " AND ".join(filters) if filters else "true"
    with driver.session() as s:
        return [dict(r) for r in s.run(f"""
            MATCH (es:EngineeringStrategy) WHERE {where}
            OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es)
            WITH es, count(DISTINCT ec) AS construct_count
            RETURN es.strategy_id AS strategy_id, es.strategy_type AS strategy_type,
                   es.description AS description, es.evidence_maturity AS evidence_maturity,
                   es.review_status AS review_status, construct_count
            ORDER BY strategy_type
        """, **params)]


def _fetch_constructs(driver, strategy_id, construct_id, pathogen_id):
    filters, params = [], {}
    if construct_id:
        filters.append("ec.construct_id = $cid"); params["cid"] = construct_id
    if strategy_id:
        filters.append("EXISTS { MATCH (ec)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid}) }")
        params["sid"] = strategy_id
    if pathogen_id:
        filters.append("EXISTS { MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid}) }")
        params["pid"] = pathogen_id
    where = " AND ".join(filters) if filters else "true"
    with driver.session() as s:
        return [dict(r) for r in s.run(f"""
            MATCH (ec:EngineeredPhageConstruct) WHERE {where}
            OPTIONAL MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(dp:DevelopmentProgram)
            WITH ec, collect(DISTINCT es.strategy_type) AS strategy_types,
                 collect(DISTINCT p.species) AS target_pathogens,
                 collect(DISTINCT dp.canonical_name) AS programs,
                 collect(DISTINCT ph.name) AS parent_phages
            RETURN ec.construct_id AS construct_id, ec.public_name AS public_name,
                   ec.construct_code AS construct_code, ec.construct_status AS construct_status,
                   ec.intended_effects AS intended_effects,
                   ec.first_public_date AS first_public_date,
                   ec.review_status AS review_status, strategy_types, target_pathogens,
                   parent_phages[0] AS parent_phage, programs, ec.created_at AS created_at
            ORDER BY created_at DESC
        """, **params)]


def _fetch_target_pathogens(driver, strategy_id, construct_id, pathogen_id):
    filters, params = [], {}
    if pathogen_id:
        filters.append("p.pathogen_id = $pid"); params["pid"] = pathogen_id
    if construct_id:
        filters.append("EXISTS { MATCH (:EngineeredPhageConstruct {construct_id: $cid})-[:TARGETS]->(p) }")
        params["cid"] = construct_id
    if strategy_id:
        filters.append("EXISTS { MATCH (:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid}) MATCH (:EngineeredPhageConstruct)-[:TARGETS]->(p) }")
        params["sid"] = strategy_id
    where = " AND ".join(filters) if filters else "true"
    with driver.session() as s:
        return [dict(r) for r in s.run(f"""
            MATCH (p:Pathogen) WHERE {where}
            OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:TARGETS]->(p)
            WITH p, count(DISTINCT ec) AS construct_count
            RETURN p.pathogen_id AS pathogen_id, p.species AS species,
                   p.resistance_mechanism AS resistance_mechanism, construct_count
            ORDER BY construct_count DESC, species
        """, **params)]


def _fetch_technical_claims(driver, construct_ids):
    if not construct_ids:
        return []
    with driver.session() as s:
        return [dict(r) for r in s.run("""
            MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec:EngineeredPhageConstruct)
            WHERE ec.construct_id IN $cids
              AND COALESCE(tc.review_status, 'approved') = 'approved'
            OPTIONAL MATCH (tc)-[:SUPPORTED_BY]->(s:SourceArtifact)
            WITH tc, ec, collect(DISTINCT s.source_id) AS source_ids
            RETURN tc.claim_id AS claim_id, tc.claim_type AS claim_type,
                   tc.claim_text AS claim_text, tc.claimant_type AS claimant_type,
                   tc.evidence_context AS evidence_context,
                   tc.claim_status AS claim_status, tc.confidence AS confidence,
                   ec.construct_id AS construct_id, ec.public_name AS construct_name,
                   source_ids
            ORDER BY tc.created_at DESC
        """, cids=construct_ids)]


def _fetch_technical_results(driver, construct_ids):
    if not construct_ids:
        return []
    with driver.session() as s:
        return [dict(r) for r in s.run("""
            MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
            WHERE ec.construct_id IN $cids
              AND COALESCE(tr.review_status, 'approved') = 'approved'
            OPTIONAL MATCH (tr)-[:REPORTED_IN]->(s:SourceArtifact)
            WITH tr, ec, collect(DISTINCT s.source_id) AS source_ids
            RETURN tr.result_id AS result_id, tr.result_type AS result_type,
                   tr.study_context AS study_context,
                   tr.outcome_direction AS outcome_direction,
                   tr.metric_name AS metric_name, tr.metric_value AS metric_value,
                   tr.metric_unit AS metric_unit, tr.sample_size AS sample_size,
                   tr.limitation_summary AS limitation_summary,
                   tr.reproducibility_status AS reproducibility_status,
                   ec.construct_id AS construct_id, ec.public_name AS construct_name,
                   source_ids
            ORDER BY tr.created_at DESC
        """, cids=construct_ids)]


def _fetch_technology_assessments(driver, strategy_id, construct_id):
    conditions, params = [], {}
    if strategy_id:
        conditions.append("(ta.subject_type = 'strategy' AND ta.subject_id = $sid)")
        conditions.append("(ta.subject_type = 'construct' AND EXISTS { MATCH (ec:EngineeredPhageConstruct {construct_id: ta.subject_id})-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid}) })")
        params["sid"] = strategy_id
    if construct_id:
        conditions.append("(ta.subject_type = 'construct' AND ta.subject_id = $cid)")
        conditions.append("(ta.subject_type = 'strategy' AND EXISTS { MATCH (:EngineeredPhageConstruct {construct_id: $cid})-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: ta.subject_id}) })")
        params["cid"] = construct_id
    where = " OR ".join(conditions) if conditions else "true"
    with driver.session() as s:
        return [dict(r) for r in s.run(f"""
            MATCH (ta:TechnologyAssessment) WHERE {where}
            RETURN ta.technology_assessment_id AS assessment_id,
                   ta.subject_type AS subject_type, ta.subject_id AS subject_id,
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
        """, **params)]


def _fetch_citations(driver, construct_ids):
    if not construct_ids:
        return []
    with driver.session() as s:
        return [dict(r) for r in s.run("""
            MATCH (ec:EngineeredPhageConstruct) WHERE ec.construct_id IN $cids
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tc)-[:SUPPORTED_BY]->(s1:SourceArtifact)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            OPTIONAL MATCH (tr)-[:REPORTED_IN]->(s2:SourceArtifact)
            WITH collect(DISTINCT s1) + collect(DISTINCT s2) AS sources
            UNWIND sources AS s WITH DISTINCT s WHERE s IS NOT NULL
            RETURN s.source_id AS source_id, s.source_type AS source_type,
                   s.title AS title, s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier
        """, cids=construct_ids)]


def _fetch_patent_families(driver, strategy_id, construct_id, pathogen_id):
    filters, params = [], {}
    if construct_id:
        filters.append("ec.construct_id = $cid"); params["cid"] = construct_id
    if strategy_id:
        filters.append("EXISTS { MATCH (ec)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid}) }")
        params["sid"] = strategy_id
    if pathogen_id:
        filters.append("EXISTS { MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid}) }")
        params["pid"] = pathogen_id
    if not filters:
        return []
    where = " AND ".join(filters)
    with driver.session() as s:
        return [dict(r) for r in s.run(f"""
            MATCH (ec:EngineeredPhageConstruct) WHERE {where}
            OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(dp:DevelopmentProgram)
            OPTIONAL MATCH (dp)-[:COVERED_BY]->(pf:PatentFamily)
            WITH pf WHERE pf IS NOT NULL
            OPTIONAL MATCH (o:Organization)-[:OWNS_PATENT]->(pf)
            WITH pf, collect(DISTINCT o.canonical_name) AS owners
            RETURN pf.patent_family_id AS patent_family_id, pf.title AS title,
                   pf.legal_status AS legal_status, pf.priority_date AS priority_date,
                   pf.jurisdictions AS jurisdictions,
                   pf.publication_numbers AS publication_numbers,
                   pf.claim_scope_summary AS claim_scope_summary, owners
            ORDER BY pf.priority_date DESC
        """, **params)]


def _aggregate_evidence_maturity(assessments, constructs):
    by_construct, by_strategy = [], []
    distribution = {"conceptual": 0, "in_vitro": 0, "in_vivo": 0, "clinical": 0}
    cid_m, sid_m = {}, {}
    for a in assessments:
        m = a.get("evidence_maturity") or "conceptual"
        if a.get("subject_type") == "construct":
            cid_m[a["subject_id"]] = m
        elif a.get("subject_type") == "strategy":
            sid_m[a["subject_id"]] = m
    for c in constructs:
        m = cid_m.get(c["construct_id"], "conceptual")
        by_construct.append({"construct_id": c["construct_id"],
                             "name": c.get("public_name"), "maturity": m})
        if m in distribution:
            distribution[m] += 1
    for sid, m in sid_m.items():
        by_strategy.append({"strategy_id": sid, "maturity": m})
    all_m = list(cid_m.values()) + list(sid_m.values())
    return {"by_construct": by_construct, "by_strategy": by_strategy,
            "distribution": distribution, "highest_maturity": _max_maturity(all_m)}


def _aggregate_risk_field(assessments, field, label):
    items = []
    for a in assessments:
        v = a.get(field)
        if v and v != "unknown":
            items.append({"subject_type": a.get("subject_type"),
                          "subject_id": a.get("subject_id"),
                          "level": v, "label": label, "summary": a.get("summary")})
    return items


def _aggregate_capability_gaps(assessments):
    gaps = []
    for a in assessments:
        v = a.get("internal_capability_gap")
        if v in ("high", "medium"):
            gaps.append({"subject_type": a.get("subject_type"),
                         "subject_id": a.get("subject_id"),
                         "gap_level": v, "summary": a.get("summary")})
    return gaps


def _build_recommended_next_steps(constructs, claims, results, assessments, evidence_maturity):
    steps = []
    if not assessments:
        steps.append("尚未生成技术评估，建议由领域专家补充评估后再做决策。")
    if claims and not results:
        steps.append("存在技术主张但缺少实验/研究结果，建议补充体外或体内数据验证。")
    d = evidence_maturity.get("distribution", {})
    if d.get("clinical", 0) == 0 and d.get("in_vivo", 0) == 0:
        steps.append("当前证据成熟度均停留在体外阶段，临床转化存在明显不确定性。")
    if any(a.get("internal_capability_gap") == "high" for a in assessments):
        steps.append("内部能力差距被评为 high，建议评估合作/引进/自建三条路径。")
    if any((a.get("safety_uncertainty") or "") == "high"
           or (a.get("manufacturability_risk") or "") == "high" for a in assessments):
        steps.append("安全性或可制造性风险高，建议在立项前完成风险专项评估。")
    if not steps:
        steps.append("建议持续观察该方向的公开证据更新，并每季度复核一次。")
    return steps


def _build_executive_summary(strategies, constructs, pathogens, claims, results, assessments):
    s_types = ", ".join(sorted({s.get("strategy_type", "") for s in strategies if s.get("strategy_type")})) or "未指定策略"
    species = ", ".join(sorted({p.get("species", "") for p in pathogens if p.get("species")})) or "未指定病原"
    return (f"本简报围绕 {s_types} 策略，覆盖 {len(constructs)} 个公开构建体、"
            f"{len(pathogens)} 个目标病原（{species}）。共收集 {len(claims)} 条技术主张、"
            f"{len(results)} 条技术结果、{len(assessments)} 份技术评估。"
            f"主张与结果已分离存储，所有关键事实均已回溯至来源对象。")


def _collect_data_gaps(constructs, claims, results, patent_families=None):
    gaps = []
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
    if not (patent_families or []):
        gaps.append("尚未关联任何专利族（PatentFamily）")
    return gaps


def _build_brief_title(strategies, constructs, pathogens):
    if len(strategies) == 1 and strategies[0].get("strategy_type"):
        subject = strategies[0]["strategy_type"]
    elif len(constructs) == 1 and constructs[0].get("public_name"):
        subject = constructs[0]["public_name"]
    elif len(pathogens) == 1 and pathogens[0].get("species"):
        subject = pathogens[0]["species"]
    else:
        subject = "工程化噬菌体技术"
    return f"技术情报简报 - {subject}"


def _link_brief_to_subjects(driver, brief_id, strategy_ids, construct_ids, pathogen_ids):
    with driver.session() as session:
        if strategy_ids:
            session.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                UNWIND $sids AS sid MATCH (es:EngineeringStrategy {strategy_id: sid})
                MERGE (b)-[:COVERS]->(es)
            """, bid=brief_id, sids=strategy_ids)
        if construct_ids:
            session.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                UNWIND $cids AS cid MATCH (ec:EngineeredPhageConstruct {construct_id: cid})
                MERGE (b)-[:COVERS]->(ec)
            """, bid=brief_id, cids=construct_ids)
        if pathogen_ids:
            session.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                UNWIND $pids AS pid MATCH (p:Pathogen {pathogen_id: pid})
                MERGE (b)-[:COVERS]->(p)
            """, bid=brief_id, pids=pathogen_ids)