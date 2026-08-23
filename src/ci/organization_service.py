# src/ci/organization_service.py 竞争对手档案
import uuid
import hashlib
from typing import Dict, List, Optional
from neo4j import Driver
from src.foundation.audit_service import log_action
from datetime import datetime, timedelta

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

def detect_material_changes(
    driver: Driver,
    organization_id: str,
    since_date: Optional[str] = None,
    days_back: int = 90
) -> Dict:
    """
    PRD 13.3: detect_material_changes
    检测组织在指定时间范围内的重大变化
    
    Args:
        driver: Neo4j 驱动
        organization_id: 组织ID
        since_date: 起始日期（格式 YYYY-MM-DD），如果为 None 则使用 days_back
        days_back: 回溯天数，默认90天
    
    Returns:
        Dict: 包含各类变化的汇总
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
                   e.event_date AS event_date,
                   e.materiality AS materiality,
                   e.confidence AS confidence
            ORDER BY e.event_date DESC
        """, oid=organization_id, since_date=since_date)
        new_events_list = [dict(record) for record in new_events]
        
        # 3. 检测新项目（在 since_date 之后创建）
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
        
        # 4. 检测状态变化的项目（需要查询历史状态，暂时通过事件推断）
        # 通过查找包含 "status" 相关的事件来推断状态变化
        status_changes = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(e:IntelligenceEvent)
            WHERE e.event_date >= $since_date
              AND (e.event_type = 'pipeline_update' 
                   OR e.event_type = 'program_discontinuation'
                   OR e.event_type = 'clinical_trial_update')
              AND e.title CONTAINS 'status' OR e.title CONTAINS 'phase' OR e.title CONTAINS 'update'
            RETURN e.event_id AS event_id,
                   e.title AS title,
                   e.event_type AS event_type,
                   e.event_date AS event_date,
                   e.factual_summary AS summary
            ORDER BY e.event_date DESC
        """, oid=organization_id, since_date=since_date)
        status_changes_list = [dict(record) for record in status_changes]
        
        # 5. 检测新合作/融资/监管事件（高重要性）
        high_impact_events = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(e:IntelligenceEvent)
            WHERE e.event_date >= $since_date
              AND e.event_type IN ['partnership', 'funding', 'regulatory_update', 'acquisition']
              AND (e.materiality = 'high' OR e.materiality IS NULL)
            RETURN e.event_id AS event_id,
                   e.event_type AS event_type,
                   e.title AS title,
                   e.event_date AS event_date,
                   e.materiality AS materiality
            ORDER BY e.event_date DESC
        """, oid=organization_id, since_date=since_date)
        high_impact_list = [dict(record) for record in high_impact_events]
        
        # 6. 统计与汇总
        summary = {
            "organization_name": org["name"],
            "organization_id": org["id"],
            "since_date": since_date,
            "detected_at": datetime.now().isoformat(),
            "total_new_events": len(new_events_list),
            "total_new_programs": len(new_programs_list),
            "total_status_changes": len(status_changes_list),
            "total_high_impact_events": len(high_impact_list),
            "changes": {
                "new_events": new_events_list,
                "new_programs": new_programs_list,
                "status_changes": status_changes_list,
                "high_impact_events": high_impact_list
            },
            "has_material_change": (
                len(new_events_list) > 0 or 
                len(new_programs_list) > 0 or 
                len(status_changes_list) > 0 or 
                len(high_impact_list) > 0
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
    
    Args:
        driver: Neo4j 驱动
        days_back: 回溯天数
        min_changes: 最少变化数量阈值
    
    Returns:
        List[Dict]: 有变化的组织列表
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