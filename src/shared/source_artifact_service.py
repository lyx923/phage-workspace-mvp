# src/shared/source_artifact_service.py
import uuid
from typing import Optional, List
from neo4j import Driver
from src.foundation.audit_service import log_action   # 如果已有 write_audit_event，可改用；这里使用已有的 log_action 并统一 action_type


def generate_source_id() -> str:
    """生成格式为 SRC:XXXXXXXX 的 SourceArtifact ID"""
    return f"SRC:{uuid.uuid4().hex[:8].upper()}"


def create_source_artifact(
    driver: Driver,
    source_type: str,          # 受控词表: pubmed, regulatory_filing, press_release, patent, conference_abstract, news_article, clinical_trial_reg
    title: str,
    url: str,
    published_date: str,       # ISO 8601, e.g., "2022-03-15"
    authors: Optional[List[str]] = None,
    publisher: Optional[str] = None,
    external_id: Optional[str] = None,  # PMID, 专利号, 监管文件编号等
    access_date: Optional[str] = None,  # 抓取日期, ISO 8601
    credibility_tier: str = "secondary",  # primary, secondary, tertiary
    actor_id: str = "system",
) -> str:
    """
    创建 SourceArtifact 节点，按 url 去重 (MERGE 语义)。
    重复调用同一 url 返回已有的 source_id。
    自动记录审计事件 (CREATE)。
    """
    authors = authors or []
    
    with driver.session() as session:
        # 使用 MERGE 基于 url 确保幂等
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

    # 记录审计事件
    log_action(
        driver,
        domain="foundation",          # 或 "ci"，但 SourceArtifact 属于共享层，建议使用 "foundation"
        action_type="CREATE",
        object_type="SourceArtifact",
        object_id=source_id,
        actor_id=actor_id,
        after_snapshot={
            "source_type": source_type,
            "title": title,
            "url": url,
            "credibility_tier": credibility_tier,
        },
        reason=f"创建 SourceArtifact: {title}",
    )

    return source_id


def get_source_artifact_by_url(driver: Driver, url: str) -> Optional[dict]:
    """根据 url 查询已有 SourceArtifact（用于调试或前置检查）"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s:SourceArtifact {url: $url})
            RETURN s
            """,
            url=url,
        ).single()
        return dict(result["s"]) if result else None