# src/ci/competitor_brief.py
from typing import Dict, Optional, List
from neo4j import Driver
from datetime import datetime
import json

from src.ci.competitor_profile import build_competitor_profile
from src.ci import organization_service
from src.ci.intelligence_product_service import create_intelligence_product


# ==================== P1-2 新增常量 ====================
EVENT_SIGNAL_MAP = {
    "acquisition": "threat", "merger": "threat", "regulatory_approval": "threat",
    "ipo": "threat", "funding": "threat", "clinical_milestone": "threat",
    "regulatory_setback": "opportunity", "clinical_failure": "opportunity",
    "partnership": "uncertainty", "regulatory_update": "uncertainty",
    "publication": "uncertainty", "conference": "uncertainty",
    "personnel_change": "uncertainty",
}


def _assign_signal_direction(event: dict) -> str:
    event_type = event.get("event_type", "")
    impact_level = event.get("impact_level", "low")
    title = event.get("title", "").lower()
    base_direction = EVENT_SIGNAL_MAP.get(event_type, "uncertainty")
    if base_direction == "uncertainty" and impact_level in ("critical", "high"):
        for kw in ["acqui", "merger", "merge", "takeover", "收购", "兼并", "合并"]:
            if kw in title:
                return "threat"
    return base_direction


def _aggregate_competitive_signals(events, claims=None, assessments=None) -> Dict:
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
        "threats": threats, "opportunities": opportunities, "uncertainties": uncertainties,
        "signal_count": len(threats) + len(opportunities) + len(uncertainties),
        "aggregation_method": "rule_based_no_llm", "aggregation_version": "0.5.0",
        "requires_expert_review": True,
        "auto_generated_note": "以上竞争信号由规则引擎自动聚合，基于图谱中已有的结构化对象，不包含 AI 推断内容。须由情报分析师审核后方可引用。",
    }


# ==================== P1 新增：白空间 / 格局矩阵 ====================

def _build_white_space_block(driver, organization_id):
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->
                  (:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(p:Pathogen)
            RETURN DISTINCT p.species AS species
        """, oid=organization_id))
    pathogen_scope = [r["species"] for r in rows if r["species"]]
    try:
        from src.ci.landscape_service import identify_landscape_white_space
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
    with driver.session() as s:
        prog_ids = [r["pid"] for r in s.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            RETURN d.program_id AS pid ORDER BY d.canonical_name LIMIT 5
        """, oid=organization_id)]
    if not prog_ids:
        return {"x_axis": [], "y_axis": [], "cells": [], "program_ids": []}
    try:
        from src.ci.landscape_service import compare_competitor_programs
        r = compare_competitor_programs(driver, prog_ids)
        return {"program_ids": prog_ids, "x_axis": r["matrix"]["x_axis"],
                "y_axis": r["matrix"]["y_axis"], "cells": r["matrix"]["cells"]}
    except Exception as e:
        return {"program_ids": prog_ids, "x_axis": [], "y_axis": [], "cells": [], "error": str(e)}


# ==================== ★ P1 质量能力接入：三个新函数 ====================

def _build_source_credibility_breakdown(driver, organization_id):
    """按来源可信度分层统计该组织引用的所有 SourceArtifact"""
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(:IntelligenceEvent)
                  -[:HAS_SOURCE]->(src:SourceArtifact)
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
    """检测该组织是否可能与其他组织重复"""
    try:
        from src.ci.entity_resolution_service import find_duplicate_candidates
        candidates = find_duplicate_candidates(driver, organization_id, min_score=0.4)
        return {
            "duplicate_candidates": candidates[:5],
            "candidate_count": len(candidates),
            "note": "疑似重复的候选，须由情报分析师人工确认后方可合并。不自动合并。",
        }
    except Exception as e:
        return {"duplicate_candidates": [], "candidate_count": 0, "error": str(e)}


def _build_conflict_summary(driver, organization_id):
    """检测该组织关联的所有构建体是否有技术冲突"""
    try:
        from src.engineering_intelligence.claim_conflict_service import detect_conflicts
        with driver.session() as s:
            cids = [r["cid"] for r in s.run("""
                MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->
                      (:DevelopmentProgram)<-[:ASSOCIATED_WITH]-(ec:EngineeredPhageConstruct)
                RETURN DISTINCT ec.construct_id AS cid
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


# ==================== 主入口 ====================

def generate_competitor_brief(
    driver: Driver,
    organization_id: str,
    days_back: int = 90,
    include_all_programs: bool = True,
    persist: bool = True,
) -> Dict:
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

    # ★ 新增：三个质量能力区块
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
        "source_credibility_breakdown": source_credibility,     # ★ 新增
        "entity_resolution_hints": entity_resolution_hints,     # ★ 新增
        "conflict_summary": conflict_summary,                   # ★ 新增
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

    for prog in profile.get("active_programs", []):
        pathogens = [p["species"] for p in prog.get("target_pathogens", []) if p.get("species")]
        brief_data["active_programs"].append({
            "name": prog["name"], "stage": prog.get("stage", "unknown"),
            "status": prog.get("status", "active"), "modality": prog.get("modality", "unknown"),
            "target_pathogens": pathogens, "program_type": prog.get("program_type", "unknown"),
        })

    for evt in profile.get("recent_events", [])[:10]:
        brief_data["recent_events"].append({
            "date": evt.get("event_date"), "type": evt.get("event_type"),
            "title": evt.get("title"), "summary": evt.get("summary"),
            "confidence": evt.get("confidence", "medium"),
            "materiality": evt.get("materiality", "medium"),
            "affected_program": evt.get("affected_program"),
        })

    # 建议下一步
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

    # ★ 新增：质量能力相关建议
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

    if persist:
        brief_id = create_intelligence_product(
            driver,
            brief_type="competitor",
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


def _fetch_citations_for_organization(driver, organization_id):
    with driver.session() as session:
        result = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(e:IntelligenceEvent)
            MATCH (e)-[:HAS_SOURCE]->(s:SourceArtifact)
            RETURN DISTINCT s.source_id AS source_id, s.source_type AS source_type,
                   s.title AS title, s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier,
                   collect(DISTINCT e.event_id) AS referenced_by_event_ids
            UNION
            MATCH (o:Organization {organization_id: $oid})<-[:DEVELOPS]-(:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(:Pathogen)<-[:TARGETS]-(:EngineeredPhageConstruct)-[:CLAIMS_ABOUT]-(tc:TechnicalClaim)
            MATCH (tc)-[:SUPPORTED_BY]->(s:SourceArtifact)
            RETURN DISTINCT s.source_id AS source_id, s.source_type AS source_type,
                   s.title AS title, s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier,
                   [] AS referenced_by_event_ids
        """, oid=organization_id)
        return [{
            "source_id": r["source_id"], "source_type": r["source_type"],
            "title": r["title"], "url": r["url"],
            "published_date": r["published_date"],
            "credibility_tier": r["credibility_tier"],
            "referenced_by_event_ids": r["referenced_by_event_ids"],
        } for r in result]


def _build_patent_landscape(patent_list):
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


def generate_technology_brief(driver, strategy_id=None, construct_id=None, pathogen_id=None, **kwargs):
    from src.engineering_intelligence.technology_brief import generate_technology_brief as _gen
    return _gen(driver, strategy_id=strategy_id, construct_id=construct_id,
                pathogen_id=pathogen_id, **kwargs)