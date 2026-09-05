# src/ci/event_service.py 情报事件
import uuid
import hashlib
from typing import Optional, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_event_id() -> str:
    """
    生成情报事件 ID。
    
    Returns:
        str: 格式为 CI:EVT:XXXXXXXX 的事件唯一标识符
    """
    return f"CI:EVT:{uuid.uuid4().hex[:8].upper()}"


def _generate_dedup_key(event_type: str, organization_id: str, title: str, event_date: str) -> str:
    """
    生成去重键，用于防止重复导入相同事件。
    
    Args:
        event_type: 事件类型（如 acquisition, funding 等）
        organization_id: 所属组织 ID
        title: 事件标题
        event_date: 事件发生日期
    
    Returns:
        str: SHA256 哈希的前 16 位，作为去重键
    """
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
    actor_id: str = "system",
) -> str:
    """
    捕获并存储情报事件（PRD 12.2）。
    
    核心功能：
        1. 自动生成去重键，检测重复事件
        2. 创建 IntelligenceEvent 节点，存储 organization_id 属性
        3. 关联组织（CONCERNS）和项目（AFFECTS）
        4. 关联来源文献（HAS_SOURCE）
        5. 记录审计日志
    
    Args:
        driver: Neo4j 数据库驱动
        event_type: 事件类型（受控词表 VOC-EVENT-TYPE）
        title: 事件标题
        factual_summary: 事实性摘要（不含推断）
        organization_id: 所属组织 ID
        program_id: 可选，关联的研发项目 ID
        event_date: 事件发生日期（YYYY-MM-DD）
        published_at: 发布日期（YYYY-MM-DD）
        source_ids: 可选，来源文献 ID 列表（SRC:XXXXXXXX）
        actor_id: 操作者标识（默认 system）
    
    Returns:
        str: 创建的事件 ID（CI:EVT:XXXXXXXX）
    
    Raises:
        ValueError: 当去重键重复或来源 ID 不存在时抛出
    """
    source_ids = source_ids or []
    dedup_key = _generate_dedup_key(event_type, organization_id, title, event_date or "")

    with driver.session() as session:
        # 1. 去重检查
        existing = session.run(
            """
            MATCH (e:IntelligenceEvent {deduplication_key: $key})
            RETURN e.event_id AS id
            """,
            key=dedup_key,
        ).single()
        if existing:
            raise ValueError(f"重复事件已存在，ID: {existing['id']}")

        event_id = generate_event_id()

        # 2. 创建事件节点，并关联组织
        session.run(
            """
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
                deduplication_key: $dedup_key,
                organization_id: $oid
            })
            WITH e
            MATCH (o:Organization {organization_id: $oid})
            CREATE (e)-[:CONCERNS]->(o)
            """,
            eid=event_id,
            etype=event_type,
            title=title,
            summary=factual_summary,
            evt_date=event_date,
            pub_at=published_at,
            dedup_key=dedup_key,
            oid=organization_id,
        )

        # 3. 关联项目（如果提供）
        if program_id:
            session.run(
                """
                MATCH (e:IntelligenceEvent {event_id: $eid})
                MATCH (d:DevelopmentProgram {program_id: $pid})
                CREATE (e)-[:AFFECTS]->(d)
                """,
                eid=event_id,
                pid=program_id,
            )

        # 4. 关联来源文献
        for src_id in source_ids:
            check = session.run(
                "MATCH (s:SourceArtifact {source_id: $sid}) RETURN s",
                sid=src_id,
            ).single()
            if not check:
                raise ValueError(f"SourceArtifact {src_id} 不存在，无法关联事件")
            session.run(
                """
                MATCH (e:IntelligenceEvent {event_id: $eid})
                MATCH (s:SourceArtifact {source_id: $sid})
                CREATE (e)-[:HAS_SOURCE]->(s)
                """,
                eid=event_id,
                sid=src_id,
            )

        # 5. 审计日志
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="IntelligenceEvent",
            object_id=event_id,
            actor_id=actor_id,
            delta={
                "event_type": event_type,
                "title": title,
                "organization_id": organization_id,
                "source_ids": source_ids,
            },
            reason=f"捕获情报事件: {title}",
        )

        return event_id