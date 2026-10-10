# src/ci/competitor_brief.py
"""
CompetitorBrief / IntelligenceProductService
合并服务（PRD 13.1 / 16.1）

本模块包含两部分：
    Part 1: Competitor Brief —— 生成竞争对手情报简报
    Part 2: IntelligenceProductService —— 情报产品（IntelligenceProduct）的
            创建、查询、审核状态更新。

竞争简报生成原则：
    - 只基于图谱中已有的结构化对象，不调用 LLM 生成事实
    - 竞争信号由规则引擎聚合，须由情报分析师审核后方可引用
    - 白空间 / 格局矩阵 / 来源可信度 / 实体消歧 / 冲突检测均为辅助信息，
      不构成最终判断
"""

# ==================================================================
# Part 1: Competitor Brief (原 competitor_brief.py)
# ==================================================================
from typing import Dict, Optional, List
from neo4j import Driver
from datetime import datetime
import json
import uuid
from src.ci.competitor_profile import build_competitor_profile
from src.ci import organization_service
from src.shared.audit_service import write_audit_event


# ---------- P1-2 常量 ----------
# 事件类型 → 信号方向基础映射
# threat        = 对内部构成威胁
# opportunity   = 对内部构成机会
# uncertainty   = 方向不明确，需要人工判断
EVENT_SIGNAL_MAP = {
    "acquisition": "threat", "merger": "threat", "regulatory_approval": "threat",
    "ipo": "threat", "funding": "threat", "clinical_milestone": "threat",
    "regulatory_setback": "opportunity", "clinical_failure": "opportunity",
    "partnership": "uncertainty", "regulatory_update": "uncertainty",
    "publication": "uncertainty", "conference": "uncertainty",
    "personnel_change": "uncertainty",
}


def _assign_signal_direction(event: dict) -> str:
    """
    判断一个情报事件对内部而言是威胁 / 机会 / 不确定。

    规则：
        1. 优先使用 EVENT_SIGNAL_MAP 中的基础方向
        2. 若基础方向为 uncertainty 且影响级别为 critical/high，
           再根据标题关键词（收购/兼并/合并等）升级为 threat

    Args:
        event: 事件字典，至少包含 event_type / impact_level / title

    Returns:
        str: "threat" / "opportunity" / "uncertainty"
    """
    event_type = event.get("event_type", "")
    impact_level = event.get("impact_level", "low")
    title = event.get("title", "").lower()
    base_direction = EVENT_SIGNAL_MAP.get(event_type, "uncertainty")
    # 基础方向不确定 + 高影响 + 标题含并购关键词 → 升级为威胁
    if base_direction == "uncertainty" and impact_level in ("critical", "high"):
        for kw in ["acqui", "merger", "merge", "takeover", "收购", "兼并", "合并"]:
            if kw in title:
                return "threat"
    return base_direction


def _aggregate_competitive_signals(events, claims=None, assessments=None) -> Dict:
    """
    规则引擎聚合竞争信号，不调用 LLM。

    将事件按方向分类为 threats / opportunities / uncertainties，
    并为每条信号生成可追溯的元数据（source_object / source_id / basis 等）。

    Args:
        events: 事件列表（通常来自 competitor_profile 的 recent_events）
        claims: 预留参数，暂未使用
        assessments: 预留参数，暂未使用

    Returns:
        Dict: 包含 threats / opportunities / uncertainties / signal_count
              以及聚合方法与声明
    """
    threats, opportunities, uncertainties = [], [], []
    for evt in events:
        direction = _assign_signal_direction(evt)
        entry = {
            "signal_text": evt.get("title", "")[:120],
            "signal_date": evt.get("event_date", ""),
            "source_object": "IntelligenceEvent",
            "source_id": evt.get("event_id", ""),
            "impact_level": organization_service._calculate_event_impact(evt),
            "confidence": "medium",
            "basis": f"event_type={evt.get('event_type')}",
            "requires_review": True,
        }
        if direction == "threat":
            threats.append(entry)
        elif direction == "opportunity":
            opportunities.append(entry)
        else:
            uncertainties.append(entry)
    return {
        "threats": threats, "opportunities": opportunities,
        "uncertainties": uncertainties,
        "signal_count": len(threats) + len(opportunities) + len(uncertainties),
        "aggregation_method": "rule_based_no_llm", "aggregation_version": "0.5.0",
        "requires_expert_review": True,
        "auto_generated_note": "以上竞争信号由规则引擎自动聚合，基于图谱中已有的结构化对象，"
                               "不包含 AI 推断内容。须由情报分析师审核后方可引用。",
    }


# ---------- P1 新增：白空间 / 格局矩阵 ----------

def _build_white_space_block(driver, organization_id):
    """
    构建白空间分析块。

    步骤：
        1. 从组织已布局的病原体范围（pathogen_scope）出发
        2. 调用 identify_landscape_white_space 识别覆盖不足的策略-病原组合
        3. 返回精简后的 underrepresented_combinations 与 summary
    """
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->
                  (:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(p:Pathogen)
            RETURN DISTINCT p.species AS species
        """, oid=organization_id))
    pathogen_scope = [r["species"] for r in rows if r["species"]]
    try:
        from src.ci.competitor_profile import identify_landscape_white_space
        ws = identify_landscape_white_space(driver, pathogen_scope=pathogen_scope or None)
        return {
            "pathogen_scope": pathogen_scope,
            "underrepresented_combinations": ws["underrepresented_combinations"][:10],
            "summary": ws["summary"], "disclaimer": ws["disclaimer"],
        }
    except Exception as e:
        return {"pathogen_scope": pathogen_scope, "underrepresented_combinations": [],
                "summary": {}, "disclaimer": "", "error": str(e)}


def _build_landscape_matrix_block(driver, organization_id):
    """
    构建格局矩阵块。

    取该组织前 5 个研发项目，调用 compare_competitor_programs 生成
    strategy × pathogen 的覆盖矩阵（x_axis / y_axis / cells）。
    """
    with driver.session() as s:
        prog_ids = [r["pid"] for r in s.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            RETURN d.program_id AS pid ORDER BY d.canonical_name LIMIT 5
        """, oid=organization_id)]
    if not prog_ids:
        return {"x_axis": [], "y_axis": [], "cells": [], "program_ids": []}
    try:
        from src.ci.competitor_profile import compare_competitor_programs
        r = compare_competitor_programs(driver, prog_ids)
        return {"program_ids": prog_ids, "x_axis": r["matrix"]["x_axis"],
                "y_axis": r["matrix"]["y_axis"], "cells": r["matrix"]["cells"]}
    except Exception as e:
        return {"program_ids": prog_ids, "x_axis": [], "y_axis": [], "cells": [], "error": str(e)}


# ---------- P1 质量能力：三个新函数 ----------

def _build_source_credibility_breakdown(driver, organization_id):
    """
    统计该组织相关来源的可信度分布。

    - 统计 total_sources
    - 按 credibility_tier 分桶（primary/secondary/tertiary/unknown）
    - 计算已评分来源的平均 credibility_score
    """
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:INVOLVES]-(e:IntelligenceEvent)
                  -[:HAS_SOURCE]->(src:SourceArtifact)
            WHERE e.organization_id = $oid
            RETURN DISTINCT src.source_id AS sid,
                   src.credibility_tier AS tier,
                   COALESCE(src.credibility_score, 0) AS score
        """, oid=organization_id))

    tiers = {"primary": 0, "secondary": 0, "tertiary": 0, "unknown": 0}
    scores = []
    for r in rows:
        t = r.get("tier") or "unknown"
        tiers[t] = tiers.get(t, 0) + 1
        if r.get("score"):
            scores.append(r["score"])

    return {
        "total_sources": len(rows),
        "by_tier": tiers,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "scored_sources": len(scores),
        "note": "来源可信度评分只反映来源渠道本身的可靠性，不代表内容正确性。",
    }


def _build_entity_resolution_hints(driver, organization_id):
    """
    检测疑似重复的组织，返回候选列表。

    只给出候选，不自动合并；须由情报分析师人工确认。
    """
    try:
        from src.ci.entity_resolution import find_duplicate_candidates
        candidates = find_duplicate_candidates(driver, organization_id, min_score=0.4)
        return {
            "duplicate_candidates": candidates[:5],
            "candidate_count": len(candidates),
            "note": "疑似重复的候选，须由情报分析师人工确认后方可合并。不自动合并。",
        }
    except Exception as e:
        return {"duplicate_candidates": [], "candidate_count": 0, "error": str(e)}


def _build_conflict_summary(driver, organization_id):
    """
    汇总该组织关联的所有构建体的技术冲突。

    - 收集该组织研发项目关联的所有 EngineeredPhageConstruct
    - 对每个构建体调用 detect_conflicts
    - 汇总 claim_status_conflicts / result_direction_conflicts
    """
    try:
        from src.engineering_intelligence.technology_assessment import detect_conflicts
        with driver.session() as s:
            cids = [r["cid"] for r in s.run("""
                MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
                OPTIONAL MATCH (ec1:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d)
                OPTIONAL MATCH (d)-[:USES_CONSTRUCT]->(ec2:EngineeredPhageConstruct)
                WITH collect(DISTINCT ec1) + collect(DISTINCT ec2) AS ecs
                UNWIND ecs AS ec
                WITH DISTINCT ec WHERE ec IS NOT NULL
                RETURN ec.construct_id AS cid
            """, oid=organization_id)]
        conflicts = {"claim_status_conflicts": [], "result_direction_conflicts": [],
                     "cross_construct_conflicts": [], "total_conflicts": 0}
        for cid in cids:
            r = detect_conflicts(driver, construct_id=cid, persist=False)
            conflicts["claim_status_conflicts"].extend(r.get("claim_status_conflicts", []))
            conflicts["result_direction_conflicts"].extend(r.get("result_direction_conflicts", []))
            conflicts["total_conflicts"] += r.get("total_conflicts", 0)
        return {
            "total_conflicts": conflicts["total_conflicts"],
            "claim_status_conflicts": conflicts["claim_status_conflicts"][:3],
            "result_direction_conflicts": conflicts["result_direction_conflicts"][:3],
            "note": "冲突检测只标记矛盾的主张/结果，不做真伪判断。",
        }
    except Exception as e:
        return {"total_conflicts": 0, "claim_status_conflicts": [],
                "result_direction_conflicts": [], "error": str(e)}


# ---------- 主入口 ----------

def generate_competitor_brief(driver: Driver, organization_id: str,
                              days_back: int = 90, include_all_programs: bool = True,
                              persist: bool = True) -> Dict:
    """
    生成竞争对手情报简报的主入口。

    流程：
        1. 构建组织档案（build_competitor_profile）
        2. 检测重大变化（detect_material_changes）
        3. 拉取引用来源（_fetch_citations_for_organization）
        4. 聚合竞争信号（_aggregate_competitive_signals）
        5. 构建专利格局 / 临床试验 / 白空间 / 格局矩阵
        6. 构建来源可信度 / 实体消歧 / 冲突摘要
        7. 组装 brief_data
        8. 可选持久化为 IntelligenceProduct

    Args:
        driver: Neo4j 驱动
        organization_id: 组织 ID
        days_back: 回溯天数（默认 90）
        include_all_programs: 预留参数
        persist: 是否持久化

    Returns:
        Dict: 完整简报数据（若 persist=True 会带 brief_id）
    """
    profile = build_competitor_profile(driver, organization_id)
    if "error" in profile:
        return profile

    changes = organization_service.detect_material_changes(driver, organization_id, days_back=days_back)
    citations = _fetch_citations_for_organization(driver, organization_id)
    competitive_assessment = _aggregate_competitive_signals(events=profile.get("recent_events", []))
    patent_landscape = _build_patent_landscape(profile.get("patent_families", []))
    clinical_trials_block = _build_clinical_trials_block(profile.get("clinical_trials", []))
    white_space_analysis = _build_white_space_block(driver, organization_id)
    landscape_matrix = _build_landscape_matrix_block(driver, organization_id)

    source_credibility = _build_source_credibility_breakdown(driver, organization_id)
    entity_resolution_hints = _build_entity_resolution_hints(driver, organization_id)
    conflict_summary = _build_conflict_summary(driver, organization_id)

    brief_data = {
        "brief_type": "competitor",
        "as_of_date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "organization": {
            "id": profile["organization"]["id"],
            "name": profile["organization"]["name"],
            "type": profile["organization"]["org_type"],
            "country": profile["organization"]["country"],
            "website": profile["organization"]["website"],
            "description": profile["organization"]["description"],
            "status": profile["organization"]["status"],
            "public_or_private": profile["organization"]["public_private"],
        },
        "active_programs": [],
        "recent_events": [],
        "competitive_assessment": competitive_assessment,
        "patent_landscape": patent_landscape,
        "clinical_trials": clinical_trials_block,
        "white_space_analysis": white_space_analysis,
        "landscape_matrix": landscape_matrix,
        "source_credibility_breakdown": source_credibility,
        "entity_resolution_hints": entity_resolution_hints,
        "conflict_summary": conflict_summary,
        "changes_summary": {
            "new_events": changes.get("total_new_events", 0),
            "new_programs": changes.get("total_new_programs", 0),
            "status_changes": changes.get("total_status_changes", 0),
            "high_impact_events": changes.get("total_high_impact_events", 0),
        },
        "data_gaps": profile.get("data_gaps", []),
        "recommended_next_steps": [],
        "citations": citations,
        "review_status": "pending",
    }

    # 精简 active_programs
    for prog in profile.get("active_programs", []):
        pathogens = [p["species"] for p in prog.get("target_pathogens", []) if p.get("species")]
        brief_data["active_programs"].append({
            "name": prog["name"], "stage": prog.get("stage", "unknown"),
            "status": prog.get("status", "active"), "modality": prog.get("modality", "unknown"),
            "target_pathogens": pathogens, "program_type": prog.get("program_type", "unknown"),
        })

    # 精简 recent_events（最多 10 条）
    for evt in profile.get("recent_events", [])[:10]:
        brief_data["recent_events"].append({
            "date": evt.get("event_date"), "type": evt.get("event_type"),
            "title": evt.get("title"), "summary": evt.get("summary"),
            "confidence": evt.get("confidence", "medium"),
            "materiality": evt.get("materiality", "medium"),
            "affected_program": evt.get("affected_program"),
        })

    # 根据各区块结果生成建议下一步
    if changes.get("has_material_change", False):
        brief_data["recommended_next_steps"].append("建议跟进近期重大事件，评估对内部战略的影响")
    if patent_landscape.get("total_families", 0) > 0:
        brief_data["recommended_next_steps"].append(
            f"对手拥有 {patent_landscape['total_families']} 个专利族，建议启动 FTO 初筛")
    if clinical_trials_block.get("active_trials"):
        brief_data["recommended_next_steps"].append(
            f"对手有 {len(clinical_trials_block['active_trials'])} 项活跃临床试验，建议持续跟踪")

    ws_summary = white_space_analysis.get("summary", {}) if isinstance(white_space_analysis, dict) else {}
    if isinstance(ws_summary, dict):
        if ws_summary.get("empty_count", 0) > 0:
            brief_data["recommended_next_steps"].append(
                f"识别到 {ws_summary['empty_count']} 个 empty white-space 组合，建议评估进入策略")
        if ws_summary.get("minimal_count", 0) > 0:
            brief_data["recommended_next_steps"].append(
                f"识别到 {ws_summary['minimal_count']} 个 minimal 覆盖组合，建议持续观察")

    if source_credibility.get("by_tier", {}).get("tertiary", 0) > 0:
        brief_data["recommended_next_steps"].append(
            f"存在 {source_credibility['by_tier']['tertiary']} 条三手来源，建议人工核验")
    if entity_resolution_hints.get("candidate_count", 0) > 0:
        brief_data["recommended_next_steps"].append(
            f"检测到 {entity_resolution_hints['candidate_count']} 个疑似重复组织，建议人工确认")
    if conflict_summary.get("total_conflicts", 0) > 0:
        brief_data["recommended_next_steps"].append(
            f"检测到 {conflict_summary['total_conflicts']} 条技术冲突，建议领域专家复核")

    if profile.get("data_gaps"):
        brief_data["recommended_next_steps"].append("补充数据缺口，完善竞争对手档案")

    # 持久化：创建 IntelligenceProduct，并回写质量能力字段
    if persist:
        brief_id = create_intelligence_product(
            driver, brief_type="competitor",
            title=f"竞争情报简报 - {profile['organization']['name']}",
            executive_summary="; ".join(
                [t["signal_text"] for t in competitive_assessment.get("threats", [])[:3]]),
            organization_id=organization_id,
            as_of_date=brief_data["as_of_date"],
            citations=citations,
            competitive_assessment=competitive_assessment,
            data_gaps=brief_data["data_gaps"],
            recommended_next_steps=brief_data["recommended_next_steps"],
            actor_id="system",
        )
        brief_data["brief_id"] = brief_id
        try:
            with driver.session() as s:
                s.run("""
                    MATCH (b:IntelligenceProduct {brief_id: $bid})
                    SET b.white_space_analysis = $ws,
                        b.landscape_matrix = $lm,
                        b.source_credibility_breakdown = $sc,
                        b.entity_resolution_hints = $er,
                        b.conflict_summary = $cf,
                        b.updated_at = datetime()
                """, bid=brief_id,
                     ws=json.dumps(white_space_analysis, ensure_ascii=False, default=str),
                     lm=json.dumps(landscape_matrix, ensure_ascii=False, default=str),
                     sc=json.dumps(source_credibility, ensure_ascii=False, default=str),
                     er=json.dumps(entity_resolution_hints, ensure_ascii=False, default=str),
                     cf=json.dumps(conflict_summary, ensure_ascii=False, default=str))
        except Exception as e:
            print(f"⚠️ 写入质量能力字段失败: {e}")
    else:
        brief_data["brief_id"] = None

    return brief_data


# ---------- citations ----------

def _fetch_citations_for_organization(driver, organization_id):
    """
    拉取该组织相关的所有引用来源。

    两条路径：
        A. 组织 ← INVOLVES ← 事件 ← HAS_SOURCE ← 来源
        B. 组织 → DEVELOPS → 项目 → 构建体 → TechnicalClaim → SUPPORTED_BY → 来源

    结果按 published_date 倒序。
    """
    citations_map: Dict[str, Dict] = {}
    with driver.session() as session:
        # 路径 A：事件来源
        result_a = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:INVOLVES]-(e:IntelligenceEvent)
                  -[:HAS_SOURCE]->(s:SourceArtifact)
            WHERE e.organization_id = $oid
            RETURN s.source_id AS source_id, s.source_type AS source_type,
                   s.title AS title, s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier,
                   collect(DISTINCT e.event_id) AS referenced_by_event_ids
        """, oid=organization_id)

        for r in result_a:
            sid = r["source_id"]
            if not sid:
                continue
            if sid not in citations_map:
                citations_map[sid] = {
                    "source_id": sid, "source_type": r["source_type"],
                    "title": r["title"], "url": r["url"],
                    "published_date": r["published_date"],
                    "credibility_tier": r["credibility_tier"],
                    "referenced_by_event_ids": list(r["referenced_by_event_ids"] or []),
                }
            else:
                citations_map[sid]["referenced_by_event_ids"].extend(
                    r["referenced_by_event_ids"] or [])

        # 路径 B：技术主张来源
        result_b = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            OPTIONAL MATCH (ec1:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d)
            OPTIONAL MATCH (d)-[:USES_CONSTRUCT]->(ec2:EngineeredPhageConstruct)
            WITH collect(DISTINCT ec1) + collect(DISTINCT ec2) AS ecs
            UNWIND ecs AS ec
            WITH DISTINCT ec WHERE ec IS NOT NULL
            MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            MATCH (tc)-[:SUPPORTED_BY]->(s:SourceArtifact)
            RETURN DISTINCT s.source_id AS source_id, s.source_type AS source_type,
                   s.title AS title, s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier
        """, oid=organization_id)

        for r in result_b:
            sid = r["source_id"]
            if not sid:
                continue
            if sid not in citations_map:
                citations_map[sid] = {
                    "source_id": sid, "source_type": r["source_type"],
                    "title": r["title"], "url": r["url"],
                    "published_date": r["published_date"],
                    "credibility_tier": r["credibility_tier"],
                    "referenced_by_event_ids": [],
                }

    return sorted(citations_map.values(),
                  key=lambda x: (x.get("published_date") or ""), reverse=True)


def _build_patent_landscape(patent_list):
    """
    构建专利格局汇总。

    - 按 legal_status 和 jurisdiction 计数
    - 按 priority_date 倒序取最近 10 个专利族
    """
    if not patent_list:
        return {"total_families": 0, "by_legal_status": {}, "by_jurisdiction": {},
                "recent_families": [], "note": "尚未收集到专利族信息"}
    by_status, by_juris = {}, {}
    for pf in patent_list:
        s = pf.get("legal_status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
        for j in (pf.get("jurisdictions") or []):
            by_juris[j] = by_juris.get(j, 0) + 1
    recent = sorted(patent_list, key=lambda x: x.get("priority_date") or "", reverse=True)[:10]
    return {
        "total_families": len(patent_list), "by_legal_status": by_status,
        "by_jurisdiction": by_juris,
        "recent_families": [{
            "patent_family_id": pf.get("patent_family_id"), "title": pf.get("title"),
            "priority_date": pf.get("priority_date"), "legal_status": pf.get("legal_status"),
            "jurisdictions": pf.get("jurisdictions") or [],
            "publication_numbers": pf.get("publication_numbers") or [],
            "claim_scope_summary": pf.get("claim_scope_summary"),
            "programs": pf.get("programs") or [],
        } for pf in recent],
        "note": "以上为公开专利族的汇总信息，不含侵权/自由实施判断。专利申请不等于技术已实现或验证。",
    }


def _build_clinical_trials_block(trial_list):
    """
    构建临床试验汇总。

    - 按 phase / status 计数
    - 筛选 active_trials（recruiting / active / not_yet_recruiting）
    """
    if not trial_list:
        return {"total_trials": 0, "by_phase": {}, "by_status": {},
                "active_trials": [], "note": "尚未收集到临床试验信息"}
    by_phase, by_status = {}, {}
    for t in trial_list:
        ph = t.get("phase") or "unknown"
        st = t.get("status") or "unknown"
        by_phase[ph] = by_phase.get(ph, 0) + 1
        by_status[st] = by_status.get(st, 0) + 1
    active = [t for t in trial_list
              if t.get("status") in ("recruiting", "active", "not_yet_recruiting")]
    return {
        "total_trials": len(trial_list), "by_phase": by_phase, "by_status": by_status,
        "active_trials": [{
            "trial_id": t.get("trial_id"), "nct_id": t.get("nct_id"),
            "title": t.get("title"), "phase": t.get("phase"), "status": t.get("status"),
            "indication": t.get("indication"), "start_date": t.get("start_date"),
            "completion_date": t.get("completion_date"), "enrollment": t.get("enrollment"),
            "programs": t.get("programs") or [],
        } for t in active],
        "note": "以上为公开登记的临床试验信息，状态以登记平台为准，不自动推断试验成败。",
    }


def generate_technology_brief(driver, strategy_id=None, construct_id=None,
                              pathogen_id=None, **kwargs):
    """
    技术简报生成入口（转发到 engineering_intelligence.technology_brief）。
    """
    from src.engineering_intelligence.technology_brief import generate_technology_brief as _gen
    return _gen(driver, strategy_id=strategy_id, construct_id=construct_id,
                pathogen_id=pathogen_id, **kwargs)


# ==================================================================
# Part 2: IntelligenceProductService
# ==================================================================

def generate_brief_id() -> str:
    """生成 IntelligenceProduct ID（格式：CI:BRIEF:XXXXXXXX）。"""
    return f"CI:BRIEF:{uuid.uuid4().hex[:8].upper()}"


def _deserialize_brief(data: Dict) -> Dict:
    """
    将 Neo4j 返回的 JSON 字符串字段反序列化为 Python 对象。

    处理的字段：citations / competitive_assessment / data_gaps / recommended_next_steps
    """
    defaults = {"citations": [], "competitive_assessment": {},
                "data_gaps": [], "recommended_next_steps": []}
    for k, default in defaults.items():
        v = data.get(k)
        if v is None:
            data[k] = default
        elif isinstance(v, str):
            try:
                data[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                data[k] = default
    return data


def create_intelligence_product(
    driver: Driver, brief_type: str, title: str, executive_summary,
    organization_id: Optional[str] = None, as_of_date: str = None,
    citations: Optional[List[Dict]] = None,
    competitive_assessment: Optional[Dict] = None,
    data_gaps: Optional[List[str]] = None,
    recommended_next_steps: Optional[List[str]] = None,
    actor_id: str = "system",
) -> str:
    """
    创建 IntelligenceProduct 节点，建立 COVERS 关系，写审计日志。

    Args:
        brief_type: 简报类型（competitor / engineered_phage_technology 等）
        title: 标题
        executive_summary: 执行摘要（str 或 list）
        organization_id: 关联组织（可选）
        as_of_date: 信息截止日期
        citations: 引用来源列表
        competitive_assessment: 竞争评估
        data_gaps: 数据缺口
        recommended_next_steps: 建议下一步
        actor_id: 操作者

    Returns:
        str: brief_id
    """
    brief_id = generate_brief_id()
    citations = citations or []
    competitive_assessment = competitive_assessment or {}
    data_gaps = data_gaps or []
    recommended_next_steps = recommended_next_steps or []

    citations_json = json.dumps(citations, ensure_ascii=False, default=str)
    assessment_json = json.dumps(competitive_assessment, ensure_ascii=False, default=str)
    gaps_json = json.dumps(data_gaps, ensure_ascii=False, default=str)
    steps_json = json.dumps(recommended_next_steps, ensure_ascii=False, default=str)

    # 统一执行摘要为字符串
    if isinstance(executive_summary, list):
        summary_str = " ".join(str(item) for item in executive_summary)
    else:
        summary_str = str(executive_summary) if executive_summary is not None else ""

    with driver.session() as session:
        session.run("""
            CREATE (b:IntelligenceProduct {
                brief_id: $brief_id, brief_type: $brief_type,
                title: $title, executive_summary: $summary,
                organization_id: $org_id, as_of_date: $as_of_date,
                citations: $citations_json,
                competitive_assessment: $assessment_json,
                data_gaps: $gaps_json,
                recommended_next_steps: $steps_json,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
        """, brief_id=brief_id, brief_type=brief_type, title=title,
             summary=summary_str, org_id=organization_id, as_of_date=as_of_date,
             citations_json=citations_json, assessment_json=assessment_json,
             gaps_json=gaps_json, steps_json=steps_json)

        # 关联组织
        if organization_id:
            session.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                MATCH (o:Organization {organization_id: $oid})
                CREATE (b)-[:COVERS]->(o)
            """, bid=brief_id, oid=organization_id)

        write_audit_event(
            driver, action_type="CREATE",
            object_type="IntelligenceProduct", object_id=brief_id,
            actor_id=actor_id,
            delta={"brief_type": brief_type, "title": title,
                   "organization_id": organization_id},
            reason=f"创建情报产品: {title}",
        )
        return brief_id


def get_intelligence_product(driver, brief_id):
    """按 ID 查询 IntelligenceProduct，返回反序列化后的字典。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (b:IntelligenceProduct {brief_id: $bid})
            OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
            RETURN b, o.organization_id AS organization_id,
                   o.canonical_name AS organization_name
        """, bid=brief_id).single()
        if not result:
            return None
        data = _deserialize_brief(dict(result["b"]))
        data["organization_id"] = result.get("organization_id")
        data["organization_name"] = result.get("organization_name")
        return data


def get_brief_by_id(driver, brief_id):
    """get_intelligence_product 的别名。"""
    return get_intelligence_product(driver, brief_id)


def get_approved_briefs(driver, brief_type=None, limit=100):
    """查询所有已批准的情报产品，按创建时间倒序。"""
    with driver.session() as session:
        if brief_type:
            result = session.run("""
                MATCH (b:IntelligenceProduct {review_status: 'approved', brief_type: $bt})
                OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
                RETURN b, o.organization_id AS organization_id,
                       o.canonical_name AS organization_name
                ORDER BY b.created_at DESC LIMIT $limit
            """, bt=brief_type, limit=limit)
        else:
            result = session.run("""
                MATCH (b:IntelligenceProduct {review_status: 'approved'})
                OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
                RETURN b, o.organization_id AS organization_id,
                       o.canonical_name AS organization_name
                ORDER BY b.created_at DESC LIMIT $limit
            """, limit=limit)
        out = []
        for r in result:
            data = _deserialize_brief(dict(r["b"]))
            data["organization_id"] = r.get("organization_id")
            data["organization_name"] = r.get("organization_name")
            out.append(data)
        return out


def get_competitor_programs(driver, organization_id):
    """
    查询某组织的所有研发项目，附带目标病原物种列表。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            OPTIONAL MATCH (d)-[:TARGETS_PATHOGEN]->(p:Pathogen)
            WITH d, collect(DISTINCT p.species) AS target_pathogens
            RETURN d.program_id AS program_id, d.canonical_name AS canonical_name,
                   d.development_stage AS development_stage, d.modality AS modality,
                   d.program_type AS program_type, d.program_status AS program_status,
                   d.review_status AS review_status, target_pathogens
            ORDER BY d.canonical_name
        """, oid=organization_id)
        return [dict(r) for r in result]


def update_intelligence_product_review_status(driver, brief_id, new_status, actor_id="system"):
    """
    更新 IntelligenceProduct 的审核状态。

    Args:
        new_status: pending / approved / rejected
    """
    valid_statuses = ["pending", "approved", "rejected"]
    if new_status not in valid_statuses:
        raise ValueError(f"状态必须是 {valid_statuses} 之一")

    with driver.session() as session:
        check = session.run(
            "MATCH (b:IntelligenceProduct {brief_id: $bid}) RETURN b",
            bid=brief_id,
        ).single()
        if not check:
            raise ValueError(f"简报 {brief_id} 不存在")
        session.run("""
            MATCH (b:IntelligenceProduct {brief_id: $bid})
            SET b.review_status = $status, b.updated_at = datetime()
        """, bid=brief_id, status=new_status)
        write_audit_event(
            driver, action_type="STATUS_CHANGE",
            object_type="IntelligenceProduct", object_id=brief_id,
            actor_id=actor_id, delta={"review_status": new_status},
            reason=f"简报审核状态更新为 {new_status}",
        )
        return True