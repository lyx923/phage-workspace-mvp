# src/ci/event_service.py 情报事件
import uuid
import hashlib
from neo4j import Driver
from src.foundation.audit_service import log_action
from typing import Optional, List

def generate_event_id() -> str:
    return f"CI:EVT:{uuid.uuid4().hex[:8].upper()}"

def _generate_dedup_key(event_type: str, organization_id: str, title: str, event_date: str) -> str:
    """PRD 12.2 去重键生成"""
    raw = f"{event_type}|{organization_id}|{title}|{event_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def capture_intelligence_event(
    driver: Driver,
    event_type: str,
    title: str,
    factual_summary: str,
    organization_id: str,
    program_id: Optional[str] = None,
    event_date: Optional[str] = None,
    published_at: Optional[str] = None,
    source_ids: Optional[List[str]] = None,
    actor_id: str = "system"
) -> str:
    """
    PRD 12.2 Action: Capture Intelligence Event
    自动生成去重键，检测重复
    """
    source_ids = source_ids or []
    dedup_key = _generate_dedup_key(event_type, organization_id, title, event_date or "")
    
    with driver.session() as session:
        # 去重检查
        existing = session.run("""
            MATCH (e:IntelligenceEvent {deduplication_key: $key})
            RETURN e.event_id AS id
        """, key=dedup_key).single()
        if existing:
            raise ValueError(f"重复事件已存在，ID: {existing['id']}")
        
        event_id = generate_event_id()
        session.run("""
            CREATE (e:IntelligenceEvent {
                event_id: $eid,
                event_type: $etype,
                title: $title,
                factual_summary: $summary,
                event_date: $evt_date,
                published_at: $pub_at,
                discovered_at: datetime(),
                created_at: datetime(),
                confidence: 'medium',
                materiality: 'medium',
                review_status: 'pending',
                deduplication_key: $dedup_key
            })
            WITH e
            MATCH (o:Organization {organization_id: $oid})
            CREATE (e)-[:CONCERNS]->(o)
        """, eid=event_id, etype=event_type, title=title, summary=factual_summary,
           evt_date=event_date, pub_at=published_at, dedup_key=dedup_key, oid=organization_id)
        
        # 关联项目（如果提供）
        if program_id:
            session.run("""
                MATCH (e:IntelligenceEvent {event_id: $eid})
                MATCH (d:DevelopmentProgram {program_id: $pid})
                CREATE (e)-[:AFFECTS]->(d)
            """, eid=event_id, pid=program_id)
        
        # 关联来源（SourceArtifact）
        for src_id in source_ids:
            session.run("""
                MATCH (e:IntelligenceEvent {event_id: $eid})
                MATCH (s:SourceArtifact {source_id: $src_id})
                CREATE (e)-[:SUPPORTED_BY]->(s)
            """, eid=event_id, src_id=src_id)
        
        log_action(driver, domain="ci", action_type="CAPTURE_EVENT",
                   object_type="IntelligenceEvent", object_id=event_id, actor_id=actor_id)
        
        return event_id