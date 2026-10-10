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
    生成去重键，用于识别多来源对同一事件的重复报道。

    去重维度：event_type + organization_id + title + event_date
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
    merge_on_duplicate: bool = True,
) -> str:
    """
    捕获并存储情报事件（PRD 12.2 / MCI-12 / v0.6 P0-2）。

    MCI-12 语义（多来源事件合并）：
      - 由 (event_type, organization_id, title, event_date) 生成 deduplication_key
      - 若已有相同 key 的事件：
          · merge_on_duplicate=True（默认）：
              合并新的 source_ids / INVOLVES / AFFECTS 到已有事件，返回该 event_id
          · merge_on_duplicate=False：
              抛 ValueError（旧的严格去重语义，仅在需要绝对唯一性时使用）
      - 若不存在：新建 IntelligenceEvent

    v0.6 统一约定：
      - 来源层物理节点统一为 SourceArtifact（不再使用 EvidenceSource）
      - source_ids 中的每一项必须是 create_source_artifact() 返回的 SRC:XXXXXXXX
      - 事件节点必须存 organization_id 属性
      - 事件与组织的关系类型统一为 INVOLVES

    Args:
        driver: Neo4j 驱动
        event_type: 事件类型
        title: 标题
        factual_summary: 事实摘要
        organization_id: 所属组织 ID
        program_id: 关联的研发项目 ID（可选）
        event_date: 事件发生日期
        published_at: 发布日期
        source_ids: SourceArtifact ID 列表（SRC:XXXXXXXX）
        actor_id: 操作者
        merge_on_duplicate: 是否合并重复事件（默认 True）

    Returns:
        str: 事件 ID（CI:EVT:XXXXXXXX），新建或已存在均返回
    """
    source_ids = source_ids or []
    dedup_key = _generate_dedup_key(event_type, organization_id, title, event_date or "")

    with driver.session() as session:
        # 1. 去重检查
        existing = session.run(
            """
            MATCH (e:IntelligenceEvent {deduplication_key: $key})
            RETURN e.event_id AS id
            LIMIT 1
            """,
            key=dedup_key,
        ).single()

        # ==================== 分支 A：已存在 ====================
        if existing:
            event_id = existing["id"]

            if not merge_on_duplicate:
                raise ValueError(f"重复事件已存在，ID: {event_id}")

            merged_source_ids = []
            linked_org = False
            linked_program = False

            # A0. v0.6 修复：补 organization_id 属性（幂等）
            session.run(
                """
                MATCH (e:IntelligenceEvent {event_id: $eid})
                SET e.organization_id = COALESCE(e.organization_id, $oid)
                """,
                eid=event_id,
                oid=organization_id,
            )

            # A1. 追加 SourceArtifact（幂等）
            for src_id in source_ids:
                chk = session.run(
                    "MATCH (s:SourceArtifact {source_id: $sid}) RETURN s LIMIT 1",
                    sid=src_id,
                ).single()
                if not chk:
                    raise ValueError(
                        f"SourceArtifact {src_id} 不存在，无法关联事件。"
                        f"请先调用 create_source_artifact() 创建。"
                    )

                already = session.run(
                    """
                    MATCH (e:IntelligenceEvent {event_id: $eid})-[:HAS_SOURCE]->(s:SourceArtifact {source_id: $sid})
                    RETURN 1 AS x LIMIT 1
                    """,
                    eid=event_id,
                    sid=src_id,
                ).single()
                if already:
                    continue

                session.run(
                    """
                    MATCH (e:IntelligenceEvent {event_id: $eid})
                    MATCH (s:SourceArtifact {source_id: $sid})
                    CREATE (e)-[:HAS_SOURCE]->(s)
                    """,
                    eid=event_id,
                    sid=src_id,
                )
                merged_source_ids.append(src_id)

            # A2. 补登组织（幂等）
            org_chk = session.run(
                "MATCH (o:Organization {organization_id: $oid}) RETURN o LIMIT 1",
                oid=organization_id,
            ).single()
            if org_chk:
                already = session.run(
                    """
                    MATCH (e:IntelligenceEvent {event_id: $eid})-[:INVOLVES]->(o:Organization {organization_id: $oid})
                    RETURN 1 AS x LIMIT 1
                    """,
                    eid=event_id,
                    oid=organization_id,
                ).single()
                if not already:
                    session.run(
                        """
                        MATCH (e:IntelligenceEvent {event_id: $eid})
                        MATCH (o:Organization {organization_id: $oid})
                        CREATE (e)-[:INVOLVES]->(o)
                        """,
                        eid=event_id,
                        oid=organization_id,
                    )
                    linked_org = True

            # A3. 补登项目（幂等）
            if program_id:
                prog_chk = session.run(
                    "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d LIMIT 1",
                    pid=program_id,
                ).single()
                if prog_chk:
                    already = session.run(
                        """
                        MATCH (e:IntelligenceEvent {event_id: $eid})-[:AFFECTS]->(d:DevelopmentProgram {program_id: $pid})
                        RETURN 1 AS x LIMIT 1
                        """,
                        eid=event_id,
                        pid=program_id,
                    ).single()
                    if not already:
                        session.run(
                            """
                            MATCH (e:IntelligenceEvent {event_id: $eid})
                            MATCH (d:DevelopmentProgram {program_id: $pid})
                            CREATE (e)-[:AFFECTS]->(d)
                            """,
                            eid=event_id,
                            pid=program_id,
                        )
                        linked_program = True

            # A4. 审计：LINK_CREATE（多来源合并）
            write_audit_event(
                driver,
                action_type="LINK_CREATE",
                object_type="IntelligenceEvent",
                object_id=event_id,
                actor_id=actor_id,
                delta={
                    "merge": True,
                    "merged_source_ids": merged_source_ids,
                    "linked_organization": linked_org,
                    "linked_program": linked_program,
                },
                reason=(
                    f"合并多来源到已有事件: {title}"
                    f"（新增 {len(merged_source_ids)} 个 SourceArtifact）"
                ),
            )
            return event_id

        # ==================== 分支 B：不存在，新建 ====================
        event_id = generate_event_id()

        # B1. 创建事件节点
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

        # B2. 关联组织（INVOLVES）
        session.run(
            """
            MATCH (e:IntelligenceEvent {event_id: $eid})
            MATCH (o:Organization {organization_id: $oid})
            CREATE (e)-[:INVOLVES]->(o)
            """,
            eid=event_id,
            oid=organization_id,
        )

        # B3. 关联项目（可选）
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

        # B4. 关联来源（SourceArtifact）
        for src_id in source_ids:
            chk = session.run(
                "MATCH (s:SourceArtifact {source_id: $sid}) RETURN s LIMIT 1",
                sid=src_id,
            ).single()
            if not chk:
                raise ValueError(
                    f"SourceArtifact {src_id} 不存在，无法关联事件。"
                    f"请先调用 create_source_artifact() 创建。"
                )
            session.run(
                """
                MATCH (e:IntelligenceEvent {event_id: $eid})
                MATCH (s:SourceArtifact {source_id: $sid})
                CREATE (e)-[:HAS_SOURCE]->(s)
                """,
                eid=event_id,
                sid=src_id,
            )

        # B5. 审计
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