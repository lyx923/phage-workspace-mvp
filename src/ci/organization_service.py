# src/ci/organization_service.py 竞争对手档案
import uuid
import hashlib
from typing import Dict, List, Optional
from neo4j import Driver
from src.foundation.audit_service import log_action
from datetime import datetime, timedelta

# ==================== P1-1 新增常量 ====================
EVENT_BASE_IMPACT = {
    "acquisition": "critical",
    "merger": "critical",
    "ipo": "high",
    "regulatory_approval": "high",
    "clinical_milestone": "high",
    "partnership": "medium",           # 默认中，可升级
    "regulatory_update": "medium",
    "funding": "medium",               # 可按金额升级
    "publication": "low",
    "conference": "low",
    "personnel_change": "low",
}

# 噬菌体领域关键词（用于语义升级）
PHAGE_DOMAIN_KEYWORDS = [
    "phage", "bacteriophage", "antimicrobial", "antibiotic resistance",
    "ESKAPE", "phage therapy", "phage bank", "phage cocktail",
    "噬菌体", "抗菌", "耐药"
]

# 融资金额升级阈值（美元）
FUNDING_HIGH_THRESHOLD_USD = 30_000_000      # ≥3000 万 → high
FUNDING_CRITICAL_THRESHOLD = 100_000_000     # ≥1 亿 → critical

# =========================================================


def generate_org_id() -> str:
    return f"CI:ORG:{uuid.uuid4().hex[:8].upper()}"


def create_organization(
    driver: Driver,
    canonical_name: str,
    organization_type: str = "biotech",
    aliases: Optional[List[str]] = None,
    headquarters_country: Optional[str] = None,
    website: Optional[str] = None,
    description: Optional[str] = None,
    actor_id: str = "system"
) -> str:
    """
    PRD 12.1 Action: Register Competitor
    创建组织前先查重（按名称和别名）
    """
    aliases = aliases or []
    
    with driver.session() as session:
        # 1. 查重：检查是否已存在同名的 Organization
        existing = session.run("""
            MATCH (o:Organization)
            WHERE o.canonical_name = $name OR $name IN o.aliases
            RETURN o.organization_id AS id
        """, name=canonical_name).single()
        
        if existing:
            raise ValueError(f"组织 '{canonical_name}' 已存在，ID: {existing['id']}。请使用 update 或确认是否重复。")

        # 2. 生成 ID 并创建节点
        org_id = generate_org_id()
        session.run("""
            CREATE (o:Organization {
                organization_id: $org_id,
                canonical_name: $name,
                aliases: $aliases,
                organization_type: $org_type,
                headquarters_country: $country,
                website: $website,
                description: $description,
                company_status: 'active',
                public_or_private: 'unknown',
                review_status: 'pending',
                last_verified_at: datetime(),
                created_at: datetime(),
                updated_at: datetime()
            })
        """, org_id=org_id, name=canonical_name, aliases=aliases,
            org_type=organization_type, country=headquarters_country,
            website=website, description=description)
        
        # 3. 记录审计
        log_action(driver, domain="ci", action_type="CREATE_ORGANIZATION",
                   object_type="Organization", object_id=org_id, actor_id=actor_id,
                   after_snapshot={"canonical_name": canonical_name})
        
        return org_id


def get_organization_by_name(driver: Driver, name: str):
    """根据规范名称或别名模糊查询"""
    with driver.session() as session:
        result = session.run("""
            MATCH (o:Organization)
            WHERE o.canonical_name CONTAINS $name OR ANY(alias IN o.aliases WHERE alias CONTAINS $name)
            RETURN o
        """, name=name)
        return [record['o'] for record in result]


# ==================== P1-1 新增辅助函数 ====================
def _calculate_event_impact(event: dict) -> str:
    """
    计算单个事件的影响级别。
    返回 'critical' | 'high' | 'medium' | 'low'
    """
    event_type = event.get("event_type", "")
    title = (event.get("title", "") + " " + event.get("factual_summary", "")).lower()
    
    base_impact = EVENT_BASE_IMPACT.get(event_type, "low")
    
    # 规则1：partnership 中包含噬菌体领域关键词 → 升级为 high
    if event_type == "partnership":
        if any(kw in title for kw in PHAGE_DOMAIN_KEYWORDS):
            base_impact = "high"
    
    # 规则2：funding 按金额升级
    if event_type == "funding":
        amount = event.get("funding_amount_usd", 0) or 0
        if amount >= FUNDING_CRITICAL_THRESHOLD:
            base_impact = "critical"
        elif amount >= FUNDING_HIGH_THRESHOLD_USD:
            base_impact = "high"
    
    return base_impact


def _is_high_impact(event: dict) -> bool:
    """判断事件是否为高影响（critical 或 high）"""
    return _calculate_event_impact(event) in ("critical", "high")


# ===========================================================


def detect_material_changes(
    driver: Driver,
    organization_id: str,
    since_date: Optional[str] = None,
    days_back: int = 90
) -> Dict:
    """
    PRD 13.3: detect_material_changes
    检测组织在指定时间范围内的重大变化
    返回的 new_events 条目中增加 impact_level 和 impact_basis 字段
    """
    if since_date is None:
        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    with driver.session() as session:
        # 1. 获取组织基本信息
        org = session.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.canonical_name AS name, o.organization_id AS id
        """, oid=organization_id).single()
        if not org:
            return {"error": f"组织 {organization_id} 不存在"}
        
        # 2. 检测新事件（在 since_date 之后）
        new_events = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(e:IntelligenceEvent)
            WHERE e.event_date IS NOT NULL AND e.event_date >= $since_date
            RETURN e.event_id AS event_id,
                   e.event_type AS event_type,
                   e.title AS title,
                   e.factual_summary AS factual_summary,
                   e.event_date AS event_date,
                   e.materiality AS materiality,
                   e.confidence AS confidence
            ORDER BY e.event_date DESC
        """, oid=organization_id, since_date=since_date)
        new_events_list = [dict(record) for record in new_events]
        
        # 3. 为每个事件计算 impact_level 和 impact_basis
        enhanced_events = []
        high_impact_events = []
        for evt in new_events_list:
            impact_level = _calculate_event_impact(evt)
            impact_basis = f"event_type={evt.get('event_type')}"
            if evt.get('event_type') == 'funding' and evt.get('funding_amount_usd'):
                impact_basis += f", funding_amount={evt.get('funding_amount_usd')}"
            elif evt.get('event_type') == 'partnership' and any(kw in (evt.get('title','')+evt.get('factual_summary','')).lower() for kw in PHAGE_DOMAIN_KEYWORDS):
                impact_basis += ", phage_keyword_match"
            # 添加增强字段
            evt_with_impact = evt.copy()
            evt_with_impact["impact_level"] = impact_level
            evt_with_impact["impact_basis"] = impact_basis
            enhanced_events.append(evt_with_impact)
            if impact_level in ("critical", "high"):
                high_impact_events.append(evt_with_impact)
        
        # 4. 检测新项目（在 since_date 之后创建）
        new_programs = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            WHERE d.created_at >= datetime($since_date)
            RETURN d.program_id AS program_id,
                   d.canonical_name AS name,
                   d.program_type AS program_type,
                   d.development_stage AS stage,
                   d.created_at AS created_at
            ORDER BY d.created_at DESC
        """, oid=organization_id, since_date=since_date)
        new_programs_list = [dict(record) for record in new_programs]
        
        # 5. 检测状态变化的项目（通过事件推断）
        status_changes = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(e:IntelligenceEvent)
            WHERE e.event_date >= $since_date
              AND (e.event_type = 'pipeline_update' 
                   OR e.event_type = 'program_discontinuation'
                   OR e.event_type = 'clinical_trial_update')
              AND (e.title CONTAINS 'status' OR e.title CONTAINS 'phase' OR e.title CONTAINS 'update')
            RETURN e.event_id AS event_id,
                   e.title AS title,
                   e.event_type AS event_type,
                   e.event_date AS event_date,
                   e.factual_summary AS summary
            ORDER BY e.event_date DESC
        """, oid=organization_id, since_date=since_date)
        status_changes_list = [dict(record) for record in status_changes]
        
        # 6. 汇总结果
        summary = {
            "organization_name": org["name"],
            "organization_id": org["id"],
            "since_date": since_date,
            "detected_at": datetime.now().isoformat(),
            "total_new_events": len(enhanced_events),
            "total_new_programs": len(new_programs_list),
            "total_status_changes": len(status_changes_list),
            "total_high_impact_events": len(high_impact_events),
            "changes": {
                "new_events": enhanced_events,           # 包含 impact_level 和 impact_basis
                "new_programs": new_programs_list,
                "status_changes": status_changes_list,
                "high_impact_events": high_impact_events  # 已经筛选并增强
            },
            "has_material_change": (
                len(enhanced_events) > 0 or 
                len(new_programs_list) > 0 or 
                len(status_changes_list) > 0 or 
                len(high_impact_events) > 0
            )
        }
        
        return summary


def get_organizations_with_recent_changes(
    driver: Driver,
    days_back: int = 30,
    min_changes: int = 1
) -> List[Dict]:
    """
    获取所有在指定天数内有变化的组织
    """
    since_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    with driver.session() as session:
        result = session.run("""
            MATCH (o:Organization)<-[:CONCERNS]-(e:IntelligenceEvent)
            WHERE e.event_date >= $since_date
            WITH o, COUNT(e) AS event_count
            WHERE event_count >= $min_changes
            RETURN o.organization_id AS id,
                   o.canonical_name AS name,
                   event_count
            ORDER BY event_count DESC
        """, since_date=since_date, min_changes=min_changes)
        
        return [dict(record) for record in result]