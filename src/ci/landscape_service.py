# src/ci/landscape_service.py
"""
PRD 13 函数层：竞争格局矩阵 / 工程化技术图谱 / 技术路线对比 / White-space 分析

对应 PRD 条目：
- PRD 13.2 compare_competitor_programs  → MCI-10 竞争格局矩阵
- PRD 13.4 map_engineering_landscape    → EPI-12 技术空白识别（局部）
- PRD 13.5 compare_engineering_strategies → EPI-08 技术路线对比
- PRD 13.7 identify_landscape_white_space → MCI-11 White-space 分析

边界声明（所有 white-space 输出必须带）：
- "White space" 表示在当前已收集、截至指定日期的公开证据中，覆盖较少的区域。
- 它不等于：市场上绝对无人布局、不存在未公开项目、该区域必然有商业价值、不存在专利风险。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from neo4j import Driver


# ============================================================
# 常量
# ============================================================

DEFAULT_COMPARISON_DIMENSIONS = [
    "target_pathogen",
    "clinical_indication",
    "development_stage",
    "modality",
    "engineering_strategy",
    "trial_status",
    "patent_coverage",
    "evidence_maturity",
]

MATURITY_ORDER = {
    "conceptual": 0,
    "in_vitro": 1,
    "in_vivo": 2,
    "clinical": 3,
}

WHITE_SPACE_DISCLAIMER = (
    'White space 表示在当前已收集、截至指定日期的公开证据中覆盖较少的区域。'
    '它不等于：市场上绝对无人布局、不存在未公开项目、该区域必然有商业价值、'
    '该区域不存在专利风险。'
)


# ============================================================
# 工具
# ============================================================

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _max_maturity(levels: List[str]) -> str:
    if not levels:
        return "conceptual"
    return max(levels, key=lambda x: MATURITY_ORDER.get(x, 0))


# ============================================================
# PRD 13.2 compare_competitor_programs
# ============================================================

def compare_competitor_programs(
    driver: Driver,
    program_ids: List[str],
    comparison_dimensions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    按维度对比多个 DevelopmentProgram（竞争格局矩阵）。

    参数：
        program_ids: 待对比的项目 ID 列表
        comparison_dimensions: 对比维度，默认全部 8 个维度

    返回：
        {
          "as_of_date": "...",
          "dimensions": [...],
          "programs": [ {program_id, canonical_name, organization, <每个维度的字段>}, ... ],
          "matrix": {          # 按 (strategy_type, pathogen_species) 聚合的 2D 矩阵
              "x_axis": [...], "y_axis": [...], "cells": [[...]]
          },
          "notes": [...]
        }
    """
    if not program_ids:
        raise ValueError("program_ids 不能为空")

    dims = comparison_dimensions or DEFAULT_COMPARISON_DIMENSIONS
    dims = [d for d in dims if d in DEFAULT_COMPARISON_DIMENSIONS]

    programs: List[Dict[str, Any]] = []

    with driver.session() as s:
        for pid in program_ids:
            base = s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                OPTIONAL MATCH (o:Organization)-[:DEVELOPS]->(d)
                RETURN d.program_id AS program_id,
                       d.canonical_name AS canonical_name,
                       d.development_stage AS development_stage,
                       d.program_status AS program_status,
                       d.modality AS modality,
                       o.canonical_name AS organization
            """, pid=pid).single()
            if not base:
                continue

            row: Dict[str, Any] = {
                "program_id": base["program_id"],
                "canonical_name": base["canonical_name"],
                "organization": base["organization"],
            }

            # 靶向病原
            pathogens = [r["species"] for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})-[:TARGETS_PATHOGEN]->(p:Pathogen)
                RETURN DISTINCT p.species AS species
            """, pid=pid)]
            row["target_pathogen"] = pathogens

            # 适应症（目前来自 ClinicalTrial.indication）
            indications = [r["indication"] for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})-[:HAS_TRIAL]->(ct:ClinicalTrial)
                WHERE ct.indication IS NOT NULL AND ct.indication <> ''
                RETURN DISTINCT ct.indication AS indication
            """, pid=pid)]
            row["clinical_indication"] = indications

            row["development_stage"] = base["development_stage"]
            row["modality"] = base["modality"]

            # 工程策略（只走构建体路径 IMPLEMENTS，避免 USES_STRATEGY 未定义 warning）
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

            # 临床试验
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

            # 证据成熟度（取关联构建体的 TechnologyAssessment 最高值）
            maturities = [r["m"] for r in s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d)
                OPTIONAL MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(ec)
                WHERE ta.evidence_maturity IS NOT NULL
                RETURN DISTINCT ta.evidence_maturity AS m
            """, pid=pid)]
            row["evidence_maturity"] = _max_maturity(maturities)

            # 按 dims 过滤
            filtered = {
                "program_id": row["program_id"],
                "canonical_name": row["canonical_name"],
                "organization": row["organization"],
            }
            for d in dims:
                filtered[d] = row.get(d)
            programs.append(filtered)

    # 构造 2D 矩阵：strategy_type × pathogen_species
    x_axis, y_axis, cells = _build_matrix(programs)

    return {
        "as_of_date": _today(),
        "dimensions": dims,
        "programs": programs,
        "matrix": {
            "x_axis": x_axis,
            "y_axis": y_axis,
            "cells": cells,
        },
        "notes": [
            "本矩阵仅基于当前图谱中已结构化的项目维度，不含未公开信息。",
        ],
    }


def _count_by(items: List[Dict], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        v = it.get(key) or "unknown"
        out[v] = out.get(v, 0) + 1
    return out


def _build_matrix(programs: List[Dict]) -> tuple:
    x_axis = sorted({s for p in programs for s in (p.get("engineering_strategy") or [])})
    y_axis = sorted({s for p in programs for s in (p.get("target_pathogen") or [])})
    cells: List[List[Dict]] = []
    for st in x_axis:
        row = []
        for sp in y_axis:
            progs = [
                p["program_id"] for p in programs
                if st in (p.get("engineering_strategy") or [])
                and sp in (p.get("target_pathogen") or [])
            ]
            row.append({"strategy_type": st, "pathogen_species": sp,
                        "program_ids": progs, "count": len(progs)})
        cells.append(row)
    return x_axis, y_axis, cells


# ============================================================
# PRD 13.4 map_engineering_landscape
# ============================================================

def map_engineering_landscape(
    driver: Driver,
    target_pathogen_id: Optional[str] = None,
    engineering_strategy_ids: Optional[List[str]] = None,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    绘制工程化噬菌体技术图谱。

    参数：
        target_pathogen_id: 限定某个病原菌，可为空
        engineering_strategy_ids: 限定若干策略，可为空
        as_of_date: 信息截止日期，默认今天

    返回：
        {
          as_of_date, filters,
          known_constructs, organizations, programs,
          claims, results,
          evidence_maturity_distribution,
          patent_families,
          white_spaces, uncertainties,
          disclaimer
        }
    """
    as_of_date = as_of_date or _today()
    strategy_ids = engineering_strategy_ids or []

    with driver.session() as s:
        # 构建体
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
            WITH ec,
                 collect(DISTINCT es.strategy_type) AS strategies,
                 collect(DISTINCT p.species) AS pathogens,
                 collect(DISTINCT d.canonical_name) AS programs,
                 collect(DISTINCT o.canonical_name) AS orgs
            RETURN ec.construct_id AS construct_id,
                   ec.public_name AS public_name,
                   ec.construct_status AS construct_status,
                   strategies, pathogens, programs, orgs
            ORDER BY ec.created_at DESC
        """, pid=target_pathogen_id, sids=strategy_ids)]

        construct_ids = [c["construct_id"] for c in constructs]

        # Claims / Results
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

        # 成熟度分布
        maturities = [r["m"] for r in s.run("""
            MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(ec:EngineeredPhageConstruct)
            WHERE ec.construct_id IN $cids
            RETURN DISTINCT ta.evidence_maturity AS m
        """, cids=construct_ids)] if construct_ids else []

        distribution = {"conceptual": 0, "in_vitro": 0, "in_vivo": 0, "clinical": 0}
        for m in maturities:
            if m in distribution:
                distribution[m] += 1

        # 专利族
        patents = [dict(r) for r in s.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
                  -[:COVERED_BY]->(pf:PatentFamily)
            WHERE ec.construct_id IN $cids
            RETURN DISTINCT pf.patent_family_id AS patent_family_id,
                   pf.title AS title, pf.legal_status AS legal_status
        """, cids=construct_ids)] if construct_ids else []

    # 组织和项目去重
    organizations = sorted({
        o for c in constructs for o in (c.get("orgs") or [])
    })
    programs = sorted({
        p for c in constructs for p in (c.get("programs") or [])
    })

    # White space 检测：在给定范围内 strategy × pathogen 组合中缺少构建体的
    white_spaces = _detect_white_spaces(
        driver, target_pathogen_id, strategy_ids
    )

    uncertainties = _build_uncertainties(constructs, claims, results, distribution)

    return {
        "as_of_date": as_of_date,
        "filters": {
            "target_pathogen_id": target_pathogen_id,
            "engineering_strategy_ids": strategy_ids,
        },
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


def _detect_white_spaces(
    driver: Driver,
    target_pathogen_id: Optional[str],
    strategy_ids: List[str],
) -> List[Dict[str, Any]]:
    """
    找出 strategy × pathogen 组合中缺少构建体的组合。
    范围仅限传入的 pathogen / strategy 筛选条件。
    """
    with driver.session() as s:
        # 所有相关策略
        if strategy_ids:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy)
                WHERE es.strategy_id IN $sids
                RETURN es.strategy_id AS sid, es.strategy_type AS stype
            """, sids=strategy_ids)]
        else:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy)
                RETURN es.strategy_id AS sid, es.strategy_type AS stype
                LIMIT 20
            """)]

        # 所有相关病原
        if target_pathogen_id:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen {pathogen_id: $pid})
                RETURN p.pathogen_id AS pid, p.species AS species
            """, pid=target_pathogen_id)]
        else:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen)
                RETURN p.pathogen_id AS pid, p.species AS species
                LIMIT 20
            """)]

        white: List[Dict[str, Any]] = []
        for st in strategies:
            for pa in pathogens:
                cnt = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    RETURN count(DISTINCT ec) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]
                if cnt == 0:
                    white.append({
                        "strategy_type": st["stype"],
                        "pathogen_species": pa["species"],
                        "construct_count": 0,
                        "coverage": "empty",
                    })
    return white


def _build_uncertainties(
    constructs: List[Dict],
    claims: List[Dict],
    results: List[Dict],
    distribution: Dict[str, int],
) -> List[str]:
    u: List[str] = []
    if not constructs:
        u.append("当前范围内无公开构建体")
    if claims and not results:
        u.append("存在技术主张但缺少实验结果")
    if distribution.get("clinical", 0) == 0 and distribution.get("in_vivo", 0) == 0:
        u.append("当前证据成熟度以体外为主，临床转化存在不确定性")
    if any(c.get("construct_status") == "proposed" for c in constructs):
        u.append("部分构建体仅处于 proposed 状态，未见实测数据")
    return u


# ============================================================
# PRD 13.5 compare_engineering_strategies
# ============================================================

def compare_engineering_strategies(
    driver: Driver,
    strategy_ids: List[str],
) -> Dict[str, Any]:
    """
    对比多个 EngineeringStrategy 的证据、能力、风险。

    返回：
        {
          "as_of_date",
          "strategies": [
            {strategy_id, strategy_type,
             intended_capabilities, reported_results,
             evidence_maturity, safety_uncertainties,
             manufacturing_considerations,
             known_organizations, associated_patents,
             internal_capability_gaps,
             construct_count}
          ],
          "comparison_matrix": {...}
        }
    """
    if not strategy_ids:
        raise ValueError("strategy_ids 不能为空")

    strategies: List[Dict[str, Any]] = []
    with driver.session() as s:
        for sid in strategy_ids:
            base = s.run("""
                MATCH (es:EngineeringStrategy {strategy_id: $sid})
                RETURN es.strategy_id AS sid, es.strategy_type AS stype,
                       es.description AS desc,
                       es.evidence_maturity AS em
            """, sid=sid).single()
            if not base:
                continue

            # 构建体
            constructs = [dict(r) for r in s.run("""
                MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $sid})
                RETURN ec.construct_id AS cid, ec.public_name AS name,
                       ec.construct_status AS status,
                       ec.intended_effects AS effects
            """, sid=sid)]
            cids = [c["cid"] for c in constructs]

            # Intended capabilities：从构建体的 intended_effects 汇总
            capabilities: List[str] = []
            for c in constructs:
                capabilities.extend(c.get("effects") or [])
            capabilities = sorted(set(capabilities))

            # 结果
            results = [dict(r) for r in s.run("""
                MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
                      -[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                RETURN tr.result_type AS result_type,
                       tr.study_context AS study_context,
                       tr.outcome_direction AS outcome_direction,
                       count(*) AS n
            """, sid=sid)] if cids else []

            # 评估
            assessments = [dict(r) for r in s.run("""
                MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(x)
                WHERE (x:EngineeringStrategy AND x.strategy_id = $sid)
                   OR (x:EngineeredPhageConstruct AND x.construct_id IN $cids)
                RETURN ta.evidence_maturity AS em,
                       ta.safety_uncertainty AS su,
                       ta.manufacturability_risk AS mr,
                       ta.internal_capability_gap AS icg
            """, sid=sid, cids=cids)] if cids else []

            em_list = [a["em"] for a in assessments if a.get("em")]
            if base.get("em"):
                em_list.append(base["em"])

            # 组织
            orgs = sorted({
                r["o"] for r in s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)<-[:DEVELOPS]-(o:Organization)
                    RETURN DISTINCT o.canonical_name AS o
                """, sid=sid)
            })

            # 专利族
            patents = [dict(r) for r in s.run("""
                MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)-[:COVERED_BY]->(pf:PatentFamily)
                RETURN DISTINCT pf.patent_family_id AS pid, pf.title AS title,
                       pf.legal_status AS status
            """, sid=sid)]

            strategies.append({
                "strategy_id": base["sid"],
                "strategy_type": base["stype"],
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


def _collect_levels(assessments: List[Dict], field: str) -> List[Dict[str, Any]]:
    out = []
    for a in assessments:
        v = a.get(field)
        if v and v != "unknown":
            out.append({"level": v})
    return out


def _build_strategy_matrix(strategies: List[Dict]) -> Dict[str, Any]:
    return {
        "strategy_types": [s["strategy_type"] for s in strategies],
        "construct_count": [s["construct_count"] for s in strategies],
        "evidence_maturity": [s["evidence_maturity"] for s in strategies],
        "organization_count": [len(s["known_organizations"]) for s in strategies],
        "patent_count": [len(s["associated_patents"]) for s in strategies],
    }


# ============================================================
# PRD 13.7 identify_landscape_white_space
# ============================================================

def identify_landscape_white_space(
    driver: Driver,
    pathogen_scope: Optional[List[str]] = None,
    indication_scope: Optional[List[str]] = None,
    technology_scope: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    识别当前知识图谱中的 White Space（覆盖较少的组合）。

    参数：
        pathogen_scope: 病原菌 species 列表，可为空（默认全部）
        indication_scope: 适应症名称列表，可为空（当前主要来自 ClinicalTrial.indication）
        technology_scope: strategy_type 列表，可为空（默认全部）

    返回：
        {
          as_of_date,
          filters,
          underrepresented_combinations: [
            {strategy_type, pathogen_species, construct_count,
             evidence_density, patent_density, known_competitor_count, data_quality}
          ],
          summary: {...},
          disclaimer
        }
    """
    pathogen_scope = pathogen_scope or []
    indication_scope = indication_scope or []
    technology_scope = technology_scope or []

    with driver.session() as s:
        # 病原
        if pathogen_scope:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen)
                WHERE p.species IN $sp
                RETURN p.pathogen_id AS pid, p.species AS species
            """, sp=pathogen_scope)]
        else:
            pathogens = [dict(r) for r in s.run("""
                MATCH (p:Pathogen)
                RETURN p.pathogen_id AS pid, p.species AS species
                LIMIT 30
            """)]

        # 策略
        if technology_scope:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy)
                WHERE es.strategy_type IN $st
                RETURN es.strategy_id AS sid, es.strategy_type AS stype
            """, st=technology_scope)]
        else:
            strategies = [dict(r) for r in s.run("""
                MATCH (es:EngineeringStrategy)
                RETURN es.strategy_id AS sid, es.strategy_type AS stype
                LIMIT 30
            """)]

        combos: List[Dict[str, Any]] = []
        for st in strategies:
            for pa in pathogens:
                # 构建体数
                cc = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    RETURN count(DISTINCT ec) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]

                # 证据密度：关联的 TechnicalClaim + TechnicalResult 数
                ec = s.run("""
                    MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
                          -[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    RETURN count(DISTINCT tr) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]

                # 专利密度
                pc = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)-[:COVERED_BY]->(pf:PatentFamily)
                    RETURN count(DISTINCT pf) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]

                # 竞争对手数
                oc = s.run("""
                    MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(:EngineeringStrategy {strategy_id: $sid})
                    MATCH (ec)-[:TARGETS]->(:Pathogen {pathogen_id: $pid})
                    MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)<-[:DEVELOPS]-(o:Organization)
                    RETURN count(DISTINCT o) AS c
                """, sid=st["sid"], pid=pa["pid"]).single()["c"]

                # 覆盖度评估（组合为空或只有 1 个构建体）
                if cc == 0:
                    coverage = "empty"
                elif cc == 1:
                    coverage = "minimal"
                elif cc <= 3:
                    coverage = "sparse"
                else:
                    coverage = "covered"

                combos.append({
                    "strategy_type": st["stype"],
                    "pathogen_species": pa["species"],
                    "construct_count": cc,
                    "evidence_density": ec,
                    "patent_density": pc,
                    "known_competitor_count": oc,
                    "coverage": coverage,
                    "data_quality": "ok" if cc > 0 else "insufficient",
                })

    # 只保留 empty / minimal / sparse
    underrepresented = [c for c in combos if c["coverage"] in ("empty", "minimal", "sparse")]
    underrepresented.sort(key=lambda x: (x["construct_count"], -x["evidence_density"]))

    return {
        "as_of_date": _today(),
        "filters": {
            "pathogen_scope": pathogen_scope,
            "indication_scope": indication_scope,
            "technology_scope": technology_scope,
        },
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