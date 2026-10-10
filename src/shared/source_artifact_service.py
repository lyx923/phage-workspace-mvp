# src/shared/source_artifact_service.py
"""
SourceArtifact 服务（v0.6 统一来源层物理节点）
"""
import uuid
import hashlib
from typing import Optional, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event


# v0.6：credibility_tier 受控词表（与 VOC-CREDIBILITY-TIER 一致）
VALID_CREDIBILITY_TIERS = {"primary", "secondary", "tertiary", "unknown"}


def generate_source_id() -> str:
    """生成 SourceArtifact ID（格式：SRC:XXXXXXXX）"""
    return f"SRC:{uuid.uuid4().hex[:8].upper()}"


def _fallback_url(title: str, published_date: Optional[str]) -> str:
    """url 为空时，用 title+published_date 生成一个稳定的伪 url 作为 MERGE key。"""
    raw = f"{(title or '').strip()}|{(published_date or '').strip()}"
    return f"urn:source:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def create_source_artifact(
    driver: Driver,
    source_type: str,
    title: str,
    url: str,
    published_date: str,
    authors: Optional[List[str]] = None,
    publisher: Optional[str] = None,
    external_id: Optional[str] = None,
    access_date: Optional[str] = None,
    credibility_tier: str = "secondary",
    actor_id: str = "system",
) -> str:
    """
    创建 SourceArtifact（幂等：按 url MERGE，重复调用返回已有 source_id）。

    v0.6 修复：credibility_tier 增加受控词表校验。
    """
    # v0.6：credibility_tier 校验
    if credibility_tier not in VALID_CREDIBILITY_TIERS:
        raise ValueError(
            f"credibility_tier 必须是 {sorted(VALID_CREDIBILITY_TIERS)} 之一，"
            f"当前值: {credibility_tier!r}"
        )

    authors = authors or []

    url_key = (url or "").strip()
    if not url_key:
        url_key = _fallback_url(title, published_date)

    with driver.session() as session:
        existing = session.run(
            """
            MATCH (s:SourceArtifact {url: $url})
            RETURN s.source_id AS source_id
            """,
            url=url_key,
        ).single()

        if existing and existing.get("source_id"):
            return existing["source_id"]

        source_id = generate_source_id()
        session.run(
            """
            CREATE (s:SourceArtifact {
                source_id: $source_id,
                source_type: $source_type,
                title: $title,
                url: $url,
                published_date: $published_date,
                authors: $authors,
                publisher: $publisher,
                external_id: $external_id,
                access_date: $access_date,
                credibility_tier: $credibility_tier,
                actor_id: $actor_id,
                created_at: datetime(),
                updated_at: datetime()
            })
            """,
            source_id=source_id,
            source_type=source_type,
            title=title,
            url=url_key,
            published_date=published_date or "unknown",
            authors=authors,
            publisher=publisher,
            external_id=external_id,
            access_date=access_date,
            credibility_tier=credibility_tier,
            actor_id=actor_id,
        )

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="SourceArtifact",
        object_id=source_id,
        actor_id=actor_id,
        delta={
            "initial_state": {
                "source_type": source_type,
                "title": title,
                "url": url_key,
                "credibility_tier": credibility_tier,
            }
        },
        reason=f"创建 SourceArtifact: {title}",
    )

    return source_id


def get_source_artifact_by_url(driver: Driver, url: str) -> Optional[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s:SourceArtifact {url: $url})
            RETURN s
            """,
            url=url,
        ).single()
        return dict(result["s"]) if result else None


def list_source_artifacts_for_event(driver: Driver, event_id: str) -> List[dict]:
    """查询某个 IntelligenceEvent 关联的所有 SourceArtifact。"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:IntelligenceEvent {event_id: $eid})-[:HAS_SOURCE]->(s:SourceArtifact)
            RETURN s.source_id AS source_id,
                   s.source_type AS source_type,
                   s.title AS title,
                   s.url AS url,
                   s.published_date AS published_date,
                   s.credibility_tier AS credibility_tier,
                   e.event_id AS referenced_by_event_id
            ORDER BY s.published_date DESC
            """,
            eid=event_id,
        )
        return [dict(r) for r in result]