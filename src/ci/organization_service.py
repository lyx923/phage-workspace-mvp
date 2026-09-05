# src/ci/organization_service.py 竞争对手档案
import uuid
from typing import Dict, List, Optional
from neo4j import Driver
from src.foundation.audit_service import write_audit_event
from datetime import datetime, timedelta

# ==================== 常量定义 ====================

# 事件类型 → 基础影响级别映射
EVENT_BASE_IMPACT = {
    "acquisition": "critical",
    "merger": "critical",
    "ipo": "high",
    "regulatory_approval": "high",
    "clinical_milestone": "high",
    "partnership": "medium",
    "regulatory_update": "medium",
    "funding": "medium",
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


# ==================== 核心函数 ====================

def generate_org_id() -> str:
    """
    生成组织 ID。
    
    Returns:
        str: 格式为 CI:ORG:XXXXXXXX 的组织唯一标识符
    """
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
    创建组织（竞争对手）节点（PRD 12.1）。
    
    创建前按名称和别名查重，防止重复注册。
    
    Args:
        driver: Neo4j 数据库驱动
        canonical_name: 规范名称
        organization_type: 组织类型（biotech, pharma, academic 等）
        aliases: 别名列表
        headquarters_country: 总部所在国家
        website: 官方网站 URL
        description: 组织描述
        actor_id: 操作者标识（默认 system）
    
    Returns:
        str: 创建的组织 ID（CI:ORG:XXXXXXXX）
    
    Raises:
        ValueError: 当组织名称已存在时抛出
    """
    aliases = aliases or []

    with driver.session() as session:
        # 1. 查重
        existing = session.run("""
            MATCH (o:Organization)
            WHERE o.canonical_name = $name OR $name IN o.aliases
            RETURN o.organization_id AS id
        """, name=canonical_name).single()

        if existing:
            raise ValueError(f"组织 '{canonical_name}' 已存在，ID: {existing['id']}")

        # 2. 创建节点
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

        # 3. 审计日志
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="Organization",
            object_id=org_id,
            actor_id=actor_id,
            delta={"canonical_name": canonical_name},
            reason=f"创建组织: {canonical_name}",
        )

        return org_id


def get_organization_by_name(driver: Driver, name: str):
    """
    根据规范名称或别名模糊查询组织。
    
    Args:
        driver: Neo4j 数据库驱动
        name: 组织名称（支持部分匹配）
    
    Returns:
        list: 匹配的组织节点列表
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (o:Organization)
            WHERE o.canonical_name CONTAINS $name OR ANY(alias IN o.aliases WHERE alias CONTAINS $name)
            RETURN o
        """, name=name)
        return [record['o'] for record in result]


def _calculate_event_impact(event: dict) -> str:
    """
    计算单个情报事件的影响级别（PRD P1-1）。
    
    规则：
        1. 基础映射：根据 event_type 从 EVENT_BASE_IMPACT 获取
        2. partnership 含噬菌体关键词 → 升级为 high
        3. funding 按金额升级（≥3000万 → high，≥1亿 → critical）
    
    Args:
        event: 事件字典，至少包含 event_type 和 title
    
    Returns:
        str: 影响级别（critical / high / medium / low）
    """
    event_type = event.get("event_type", "")
    title = (event.get("title", "") + " " + event.get("factual_summary", "")).lower()

    base_impact = EVENT_BASE_IMPACT.get(event_type, "low")

    # 规则1：partnership 包含噬菌体关键词 → high
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
    """
    判断事件是否为高影响（critical 或 high）。
    
    Args:
        event: 事件字典
    
    Returns:
        bool: 若影响级别为 critical 或 high 返回 True
    """
    return _calculate_event_impact(event) in ("critical", "high")


def detect_material_changes(
    driver: Driver,
    organization_id: str,
    since_date: Optional[str] = None,
    days_back: int = 90
) -> Dict:
    """
    检测组织在指定时间范围内的重大变化（PRD 13.3）。
    
    返回的 new_events 条目中增加 impact_level 和 impact_basis 字段。
    
    Args:
        driver: Neo4j 数据库驱动
        organization_id: 组织 ID
        since_date: 起始日期（YYYY-MM-DD），优先使用
        days_back: 若未指定 since_date，则回溯天数（默认 90 天）
    
    Returns:
        Dict: 包含以下字段的变化摘要：
            - organization_name: 组织名称
            - organization_id: 组织 ID
            - since_date: 检测起始日期
            - total_new_events: 新事件数
            - total_new_programs: 新项目数
            - total_status_changes: 状态变化数
            - total_high_impact_events: 高影响事件数
            - changes: 详细变化列表
            - has_material_change: 是否有重大变化
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
                "new_events": enhanced_events,
                "new_programs": new_programs_list,
                "status_changes": status_changes_list,
                "high_impact_events": high_impact_events
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
    获取所有在指定天数内有变化的组织。
    
    Args:
        driver: Neo4j 数据库驱动
        days_back: 回溯天数（默认 30 天）
        min_changes: 最少变化事件数（默认 1）
    
    Returns:
        List[Dict]: 组织列表，包含 id, name, event_count
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