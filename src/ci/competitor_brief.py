# src/ci/competitor_brief.py
from typing import Dict, Optional, List
from neo4j import Driver
from datetime import datetime
from src.ci.competitor_profile import build_competitor_profile
from src.ci import organization_service          # 改为导入整个模块
from src.ci.intelligence_product_service import create_intelligence_product


# ==================== P1-2 新增常量 ====================
EVENT_SIGNAL_MAP = {
    "acquisition": "threat",
    "merger": "threat",
    "regulatory_approval": "threat",
    "ipo": "threat",
    "funding": "threat",
    "clinical_milestone": "threat",
    "regulatory_setback": "opportunity",
    "clinical_failure": "opportunity",
    "partnership": "uncertainty",
    "regulatory_update": "uncertainty",
    "publication": "uncertainty",
    "conference": "uncertainty",
    "personnel_change": "uncertainty",
}


def _assign_signal_direction(event: dict) -> str:
    """
    信号方向分配：综合 event_type 和 impact_level 判断。
    当 impact_level 为 critical/high 且包含竞争对手直接行动关键词时，
    优先将信号归入 threats，覆盖默认的 uncertainty 分类。
    """
    event_type = event.get("event_type", "")
    impact_level = event.get("impact_level", "low")
    title = event.get("title", "").lower()

    # 基础映射
    base_direction = EVENT_SIGNAL_MAP.get(event_type, "uncertainty")

    # 覆盖规则：高影响的 partnership/合作若包含竞品关键词 → threat
    if base_direction == "uncertainty" and impact_level in ("critical", "high"):
        COMPETITIVE_ACTION_KEYWORDS = [
            "acqui", "merger", "merge", "takeover",
            "收购", "兼并", "合并"
        ]
        if any(kw in title for kw in COMPETITIVE_ACTION_KEYWORDS):
            return "threat"
    return base_direction


def _aggregate_competitive_signals(
    events: List[Dict],
    claims: List[Dict] = None,
    assessments: List[Dict] = None
) -> Dict:
    """
    基于已检索的结构化对象，规则聚合竞争信号。
    不调用 LLM，不创造事实。
    """
    threats = []
    opportunities = []
    uncertainties = []

    # 来自 IntelligenceEvent
    for evt in events:
        direction = _assign_signal_direction(evt)
        signal_entry = {
            "signal_text": evt.get("title", "")[:120],
            "signal_date": evt.get("event_date", ""),
            "source_object": "IntelligenceEvent",
            "source_id": evt.get("event_id", ""),
            "impact_level": organization_service._calculate_event_impact(evt),
            "confidence": "medium",
            "basis": f"event_type={evt.get('event_type')}",
            "requires_review": True
        }
        if direction == "threat":
            threats.append(signal_entry)
        elif direction == "opportunity":
            opportunities.append(signal_entry)
        else:
            uncertainties.append(signal_entry)

    return {
        "threats": threats,
        "opportunities": opportunities,
        "uncertainties": uncertainties,
        "signal_count": len(threats) + len(opportunities) + len(uncertainties),
        "aggregation_method": "rule_based_no_llm",
        "aggregation_version": "0.5.0",
        "requires_expert_review": True,
        "auto_generated_note": (
            "以上竞争信号由规则引擎自动聚合，基于图谱中已有的结构化对象，"
            "不包含 AI 推断内容。须由情报分析师审核后方可引用。"
        )
    }


# ==================== 原 generate_competitor_brief 修改 ====================
def generate_competitor_brief(
    driver: Driver,
    organization_id: str,
    days_back: int = 90,
    include_all_programs: bool = True,
    persist: bool = True,
) -> Dict:
    """
    PRD 16.1: 生成竞争者情报简报（Competitor Intelligence Brief）
    整合档案、变化检测和评估，输出结构化 JSON。
    若 persist=True，则将简报持久化为 IntelligenceProduct 节点，并返回 brief_id。
    """
    # 1. 获取档案
    profile = build_competitor_profile(driver, organization_id)
    if "error" in profile:
        return profile

    # 2. 获取变化检测
    changes = organization_service.detect_material_changes(
        driver, organization_id, days_back=days_back
    )

    # 3. 查询 citations
    citations = _fetch_citations_for_organization(driver, organization_id)

    # 4. 聚合竞争信号（P1-2）
    competitive_assessment = _aggregate_competitive_signals(
        events=profile.get("recent_events", [])
    )

    # 5. 专利与临床试验区块
    patent_landscape = _build_patent_landscape(profile.get("patent_families", []))
    clinical_trials_block = _build_clinical_trials_block(
        profile.get("clinical_trials", [])
    )

    # 6. 构建简报数据
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
            "public_or_private": profile["organization"]["public_private"]
        },
        "active_programs": [],
        "recent_events": [],
        "competitive_assessment": competitive_assessment,
        "patent_landscape": patent_landscape,
        "clinical_trials": clinical_trials_block,
        "changes_summary": {
            "new_events": changes.get("total_new_events", 0),
            "new_programs": changes.get("total_new_programs", 0),
            "status_changes": changes.get("total_status_changes", 0),
            "high_impact_events": changes.get("total_high_impact_events", 0)
        },
        "data_gaps": profile.get("data_gaps", []),
        "recommended_next_steps": [],
        "citations": citations,
        "review_status": "pending"
    }

    # 7. 填充项目信息
    for prog in profile.get("active_programs", []):
        pathogens = [
            p["species"] for p in prog.get("target_pathogens", []) if p.get("species")
        ]
        brief_data["active_programs"].append({
            "name": prog["name"],
            "stage": prog.get("stage", "unknown"),
            "status": prog.get("status", "active"),
            "modality": prog.get("modality", "unknown"),
            "target_pathogens": pathogens,
            "program_type": prog.get("program_type", "unknown")
        })

    # 8. 填充事件信息
    for evt in profile.get("recent_events", [])[:10]:
        brief_data["recent_events"].append({
            "date": evt.get("event_date"),
            "type": evt.get("event_type"),
            "title": evt.get("title"),
            "summary": evt.get("summary"),
            "confidence": evt.get("confidence", "medium"),
            "materiality": evt.get("materiality", "medium"),
            "affected_program": evt.get("affected_program")
        })

    # 9. 生成推荐下一步
    if changes.get("has_material_change", False):
        brief_data["recommended_next_steps"].append(
            "建议跟进近期重大事件，评估对内部战略的影响"
        )
    if patent_landscape.get("total_families", 0) > 0:
        brief_data["recommended_next_steps"].append(
            f"对手拥有 {patent_landscape['total_families']} 个专利族，建议启动 FTO 初筛"
        )
    if clinical_trials_block.get("active_trials"):
        brief_data["recommended_next_steps"].append(
            f"对手有 {len(clinical_trials_block['active_trials'])} 项活跃临床试验，建议持续跟踪"
        )
    if profile.get("data_gaps"):
        brief_data["recommended_next_steps"].append(
            "补充数据缺口，完善竞争对手档案"
        )

    # 10. 持久化
    if persist:
        brief_id = create_intelligence_product(
            driver,
            brief_type="competitor",
            title=f"竞争情报简报 - {profile['organization']['name']}",
            executive_summary="; ".join(
                [t["signal_text"] for t in competitive_assessment.get("threats", [])[:3]]
            ),
            organization_id=organization_id,
            as_of_date=brief_data["as_of_date"],
            citations=citations,
            competitive_assessment=competitive_assessment,
            data_gaps=brief_data["data_gaps"],
            recommended_next_steps=brief_data["recommended_next_steps"],
            actor_id="system",
        )
        brief_data["brief_id"] = brief_id
    else:
        brief_data["brief_id"] = None

    return brief_data


def _fetch_citations_for_organization(driver: Driver, organization_id: str) -> List[Dict]:
    """
    查询组织相关的 SourceArtifact，返回 citations 列表。
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(e:IntelligenceEvent)
            MATCH (e)-[:HAS_SOURCE]->(s:SourceArtifact)
            RETURN DISTINCT s.source_id AS source_id,
                   s.source_type AS source_type,
                   s.title AS title,
                   s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier,
                   collect(DISTINCT e.event_id) AS referenced_by_event_ids
            UNION
            MATCH (o:Organization {organization_id: $oid})<-[:DEVELOPS]-(:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(:Pathogen)<-[:TARGETS]-(:EngineeredPhageConstruct)-[:CLAIMS_ABOUT]->(tc:TechnicalClaim)
            MATCH (tc)-[:SUPPORTED_BY]->(s:SourceArtifact)
            RETURN DISTINCT s.source_id AS source_id,
                   s.source_type AS source_type,
                   s.title AS title,
                   s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier,
                   [] AS referenced_by_event_ids
            """,
            oid=organization_id,
        )
        citations = []
        for record in result:
            citations.append({
                "source_id": record["source_id"],
                "source_type": record["source_type"],
                "title": record["title"],
                "url": record["url"],
                "published_date": record["published_date"],
                "credibility_tier": record["credibility_tier"],
                "referenced_by_event_ids": record["referenced_by_event_ids"],
            })
        return citations


# ============================================================
# 专利 / 临床试验区块聚合
# ============================================================

def _build_patent_landscape(patent_list: List[Dict]) -> Dict:
    """
    把专利族整理成简报里的 patent_landscape 区块。
    只做结构化聚合，不做侵权/自由实施判断。
    """
    if not patent_list:
        return {
            "total_families": 0,
            "by_legal_status": {},
            "by_jurisdiction": {},
            "recent_families": [],
            "note": "尚未收集到专利族信息"
        }

    by_status: Dict[str, int] = {}
    by_juris: Dict[str, int] = {}
    for pf in patent_list:
        status = pf.get("legal_status") or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        for j in (pf.get("jurisdictions") or []):
            by_juris[j] = by_juris.get(j, 0) + 1

    recent = sorted(
        patent_list,
        key=lambda x: x.get("priority_date") or "",
        reverse=True
    )[:10]

    return {
        "total_families": len(patent_list),
        "by_legal_status": by_status,
        "by_jurisdiction": by_juris,
        "recent_families": [
            {
                "patent_family_id": pf.get("patent_family_id"),
                "title": pf.get("title"),
                "priority_date": pf.get("priority_date"),
                "legal_status": pf.get("legal_status"),
                "jurisdictions": pf.get("jurisdictions") or [],
                "publication_numbers": pf.get("publication_numbers") or [],
                "claim_scope_summary": pf.get("claim_scope_summary"),
                "programs": pf.get("programs") or [],
            }
            for pf in recent
        ],
        "note": (
            "以上为公开专利族的汇总信息，不含侵权/自由实施判断。"
            "专利申请不等于技术已实现或验证。"
        )
    }


def _build_clinical_trials_block(trial_list: List[Dict]) -> Dict:
    """
    把临床试验整理成简报里的 clinical_trials 区块。
    """
    if not trial_list:
        return {
            "total_trials": 0,
            "by_phase": {},
            "by_status": {},
            "active_trials": [],
            "note": "尚未收集到临床试验信息"
        }

    by_phase: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for t in trial_list:
        ph = t.get("phase") or "unknown"
        st = t.get("status") or "unknown"
        by_phase[ph] = by_phase.get(ph, 0) + 1
        by_status[st] = by_status.get(st, 0) + 1

    active = [
        t for t in trial_list
        if t.get("status") in ("recruiting", "active", "not_yet_recruiting")
    ]

    return {
        "total_trials": len(trial_list),
        "by_phase": by_phase,
        "by_status": by_status,
        "active_trials": [
            {
                "trial_id": t.get("trial_id"),
                "nct_id": t.get("nct_id"),
                "title": t.get("title"),
                "phase": t.get("phase"),
                "status": t.get("status"),
                "indication": t.get("indication"),
                "start_date": t.get("start_date"),
                "completion_date": t.get("completion_date"),
                "enrollment": t.get("enrollment"),
                "programs": t.get("programs") or [],
            }
            for t in active
        ],
        "note": (
            "以上为公开登记的临床试验信息，状态以登记平台为准，"
            "不自动推断试验成败。"
        )
    }


# ============================================================
# 兼容旧入口
# ============================================================

def generate_technology_brief(
    driver: Driver,
    strategy_id: Optional[str] = None,
    construct_id: Optional[str] = None,
    pathogen_id: Optional[str] = None,
    **kwargs,
) -> Dict:
    """转发到 engineering_intelligence.technology_brief（保留旧入口兼容）"""
    from src.engineering_intelligence.technology_brief import (
        generate_technology_brief as _gen,
    )
    return _gen(
        driver,
        strategy_id=strategy_id,
        construct_id=construct_id,
        pathogen_id=pathogen_id,
        **kwargs,
    )