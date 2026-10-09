# src/shared/source_artifact_service.py
"""
SourceArtifact 服务（v0.6 统一来源层物理节点）

- 唯一 Label: SourceArtifact
- 唯一 ID 格式: SRC:XXXXXXXX（大写 8 位 hex）
- 唯一 MERGE key: url（若 url 为空则用 title+published_date 兜底）
- 不允许使用 EvidenceSource / SRC-xxxx 等旧格式

引用关系（由其他服务建立）：
  (IntelligenceEvent)-[:HAS_SOURCE]->(SourceArtifact)
  (TechnicalClaim)-[:SUPPORTED_BY]->(SourceArtifact)
  (TechnicalResult)-[:REPORTED_IN]->(SourceArtifact)
  (CompetitorAssessment)-[:CITES]->(SourceArtifact)
"""
import uuid
import hashlib
from typing import Optional, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event


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

    Args:
        driver: Neo4j 驱动
        source_type: 来源类型（受控词表）
        title: 标题
        url: 原始 URL 或 DOI（若为空，用 title+published_date 生成 urn）
        published_date: 发布日期（YYYY-MM-DD 或 "unknown"）
        authors: 作者列表
        publisher: 出版机构
        external_id: PMID / 专利号 / 监管文件编号
        access_date: 抓取日期
        credibility_tier: primary / secondary / tertiary
        actor_id: 操作者

    Returns:
        str: source_id（SRC:XXXXXXXX）
    """
    authors = authors or []

    # 规范化 url：空 url 用 urn 兜底，避免多个空 url 节点被 MERGE 成一个
    url_key = (url or "").strip()
    if not url_key:
        url_key = _fallback_url(title, published_date)

    with driver.session() as session:
        # 幂等：先查
        existing = session.run(
            """
            MATCH (s:SourceArtifact {url: $url})
            RETURN s.source_id AS source_id
            """,
            url=url_key,
        ).single()

        if existing and existing.get("source_id"):
            return existing["source_id"]

        # 新建
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
    """
    查询某个 IntelligenceEvent 关联的所有 SourceArtifact。
    用于 CompetitorBrief.citations 的生成。
    """
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