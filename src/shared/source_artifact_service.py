# src/shared/source_artifact_service.py
import uuid
from typing import Optional, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_source_id() -> str:
    return f"SRC:{uuid.uuid4().hex[:8].upper()}"


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
    authors = authors or []

    with driver.session() as session:
        result = session.run(
            """
            MERGE (s:SourceArtifact {url: $url})
            ON CREATE SET
                s.source_id = $source_id,
                s.source_type = $source_type,
                s.title = $title,
                s.published_date = $published_date,
                s.authors = $authors,
                s.publisher = $publisher,
                s.external_id = $external_id,
                s.access_date = $access_date,
                s.credibility_tier = $credibility_tier,
                s.actor_id = $actor_id,
                s.created_at = datetime(),
                s.updated_at = datetime()
            ON MATCH SET
                s.updated_at = datetime()
            RETURN s.source_id AS source_id
            """,
            source_id=generate_source_id(),
            url=url,
            source_type=source_type,
            title=title,
            published_date=published_date,
            authors=authors,
            publisher=publisher,
            external_id=external_id,
            access_date=access_date,
            credibility_tier=credibility_tier,
            actor_id=actor_id,
        )
        record = result.single()
        source_id = record["source_id"]

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="SourceArtifact",
        object_id=source_id,
        actor_id=actor_id,
        delta={
            "source_type": source_type,
            "title": title,
            "url": url,
            "credibility_tier": credibility_tier,
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