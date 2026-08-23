# src/ci/competitor_profile.py
from typing import Dict, List, Optional
from neo4j import Driver
from datetime import datetime

def build_competitor_profile(
    driver: Driver,
    organization_id: str,
    as_of_date: Optional[str] = None
) -> Dict:
    """
    PRD 13.1: build_competitor_profile
    生成竞争对手完整档案
    """
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")
    
    with driver.session() as session:
        # 1. 获取组织基本信息
        org_result = session.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.organization_id AS id,
                   o.canonical_name AS name,
                   o.aliases AS aliases,
                   o.organization_type AS org_type,
                   o.headquarters_country AS country,
                   o.website AS website,
                   o.company_status AS status,
                   o.public_or_private AS public_private,
                   o.description AS description,
                   o.review_status AS review_status,
                   o.last_verified_at AS last_verified
        """, oid=organization_id).single()
        
        if not org_result:
            return {"error": f"组织 {organization_id} 不存在"}
        
        org_data = dict(org_result)
        
        # 2. 获取研发项目（修改查询，避免 DISTINCT 问题）
        programs = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            OPTIONAL MATCH (d)-[:TARGETS]->(p:Pathogen)
            WITH d, COLLECT(DISTINCT {
                pathogen_id: p.pathogen_id,
                species: p.species
            }) AS target_pathogens
            RETURN d.program_id AS program_id,
                   d.canonical_name AS name,
                   d.program_type AS program_type,
                   d.development_stage AS stage,
                   d.program_status AS status,
                   d.modality AS modality,
                   d.review_status AS review_status,
                   target_pathogens
            ORDER BY d.created_at DESC
        """, oid=organization_id)
        program_list = [dict(record) for record in programs]
        
        # 3. 获取情报事件（按时间倒序）
        events = session.run("""
            MATCH (o:Organization {organization_id: $oid})<-[:CONCERNS]-(e:IntelligenceEvent)
            OPTIONAL MATCH (e)-[:AFFECTS]->(d:DevelopmentProgram)
            RETURN e.event_id AS event_id,
                   e.event_type AS event_type,
                   e.title AS title,
                   e.factual_summary AS summary,
                   e.event_date AS event_date,
                   e.published_at AS published_at,
                   e.confidence AS confidence,
                   e.materiality AS materiality,
                   e.review_status AS review_status,
                   d.canonical_name AS affected_program
            ORDER BY e.event_date DESC
        """, oid=organization_id)
        event_list = [dict(record) for record in events]
        
        # 4. 统计信息
        stats = {
            "total_programs": len(program_list),
            "active_programs": sum(1 for p in program_list if p.get('status') == 'active'),
            "total_events": len(event_list),
            "recent_events": sum(1 for e in event_list if e.get('event_date') and e['event_date'] > "2026-01-01"),
            "pathogens_covered": list(set(
                p['species'] for prog in program_list 
                for p in prog.get('target_pathogens', []) 
                if p.get('species')
            ))
        }
        
        # 5. 数据缺口
        gaps = []
        if not program_list:
            gaps.append("无公开研发项目信息")
        if not event_list:
            gaps.append("无近期情报事件")
        if not org_data.get('website'):
            gaps.append("缺少官方网站")
        if not org_data.get('description'):
            gaps.append("缺少公司描述")
        if not org_data.get('public_private') or org_data['public_private'] == 'unknown':
            gaps.append("公司类型（上市/私有）未确认")
        
        return {
            "organization": org_data,
            "active_programs": program_list,
            "recent_events": event_list,
            "target_pathogens": stats["pathogens_covered"],
            "statistics": stats,
            "data_gaps": gaps,
            "as_of_date": as_of_date,
            "generated_at": datetime.now().isoformat()
        }

def list_organizations(driver: Driver) -> List[Dict]:
    """列出所有组织（用于选择）"""
    with driver.session() as session:
        result = session.run("""
            MATCH (o:Organization)
            RETURN o.organization_id AS id,
                   o.canonical_name AS name,
                   o.organization_type AS type,
                   o.headquarters_country AS country
            ORDER BY o.canonical_name
        """)
        return [dict(record) for record in result]