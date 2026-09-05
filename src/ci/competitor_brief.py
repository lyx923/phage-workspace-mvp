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
        # 使用新函数计算方向
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

    # MVP 阶段暂不处理 claims 和 assessments（留空）

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
    changes = organization_service.detect_material_changes(driver, organization_id, days_back=days_back)

    # 3. 查询 citations
    citations = _fetch_citations_for_organization(driver, organization_id)

    # 4. 聚合竞争信号（P1-2）
    competitive_assessment = _aggregate_competitive_signals(
        events=profile.get("recent_events", [])
    )

    # 5. 构建简报数据
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

    # 6. 填充项目信息
    for prog in profile.get("active_programs", []):
        pathogens = [p["species"] for p in prog.get("target_pathogens", []) if p.get("species")]
        brief_data["active_programs"].append({
            "name": prog["name"],
            "stage": prog.get("stage", "unknown"),
            "status": prog.get("status", "active"),
            "modality": prog.get("modality", "unknown"),
            "target_pathogens": pathogens,
            "program_type": prog.get("program_type", "unknown")
        })

    # 7. 填充事件信息
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

    # 8. 生成推荐下一步
    if changes.get("has_material_change", False):
        brief_data["recommended_next_steps"].append("建议跟进近期重大事件，评估对内部战略的影响")
    if profile.get("data_gaps"):
        brief_data["recommended_next_steps"].append("补充数据缺口，完善竞争对手档案")

    # 9. 持久化
    if persist:
        brief_id = create_intelligence_product(
            driver,
            brief_type="competitor",
            title=f"竞争情报简报 - {profile['organization']['name']}",
            executive_summary="; ".join([t["signal_text"] for t in competitive_assessment.get("threats", [])[:3]]),
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
    修改：使用 DISTINCT 并按 source_id 去重，同时收集所有引用该来源的事件 ID。
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


# 保留原 generate_technology_brief（占位）
def generate_technology_brief(
    driver: Driver,
    strategy_id: Optional[str] = None,
    construct_id: Optional[str] = None
) -> Dict:
    return {"message": "Technology Brief - 待实现"}