# src/shared/evidence_source.py
"""
Foundation 层共享对象服务。

本文件承载 CI 域和 Scientific 域共用的基础对象服务：

- SourceArtifact：来源工件（v0.6 统一来源层物理节点）
- Pathogen：病原体（跨域 MERGE 语义）

历史：
- 原 src/shared/source_artifact_service.py 的内容合并至此
- 原 src/shared/pathogen_service.py 的内容合并至此
"""
import uuid
import hashlib
from typing import Optional, List, Dict

from neo4j import Driver

from src.shared.audit_service import write_audit_event


# ============================================================
# Part 1: SourceArtifact
# ============================================================

# v0.6：credibility_tier 受控词表（与 VOC-CREDIBILITY-TIER 一致）
VALID_CREDIBILITY_TIERS = {"primary", "secondary", "tertiary", "unknown"}


def generate_source_id() -> str:
    """生成 SourceArtifact ID（格式：SRC:XXXXXXXX）。"""
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
        source_type: 来源类型
        title: 标题
        url: URL（可为空，降级用 title+published_date 作为伪 url）
        published_date: 发表日期
        authors / publisher / external_id / access_date: 可选
        credibility_tier: 可信度等级（primary / secondary / tertiary / unknown）
        actor_id: 操作者

    Returns:
        str: source_id
    """
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
        # 幂等检查
        existing = session.run(
            """
            MATCH (s:SourceArtifact {url: $url})
            RETURN s.source_id AS source_id
            """,
            url=url_key,
        ).single()

        if existing and existing.get("source_id"):
            return existing["source_id"]

        # 创建节点
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
    """按 url 查询 SourceArtifact。"""
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


# ============================================================
# Part 2: Pathogen
# （从原 src/shared/pathogen_service.py 合并而来）
# ============================================================

def generate_pathogen_id() -> str:
    """生成 Pathogen ID（格式：PATH-XXXXXXXX）。"""
    return f"PATH-{uuid.uuid4().hex[:8].upper()}"


def get_or_create_pathogen(
    driver: Driver,
    species: str,
    genus: Optional[str] = None,
    gram_stain: Optional[str] = None,
    pathogen_type: str = "bacteria",
    eskape_category: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    external_ids: Optional[Dict[str, str]] = None,
    actor_id: str = "system",
) -> str:
    """
    获取或创建病原体节点（MERGE 语义：species 相同永远返回同一节点）。

    跨域共享：Scientific Domain 和 CI Domain 通过此函数共享同一个 Pathogen 节点。

    Args:
        species: 物种名（MERGE key）
        genus / gram_stain / pathogen_type / eskape_category: 分类信息
        aliases / external_ids: 别名 / 外部 ID
        actor_id: 操作者

    Returns:
        str: pathogen_id
    """
    aliases = aliases or []
    if external_ids is None or not external_ids:
        external_ids = None

    with driver.session() as session:
        result = session.run(
            """
            MERGE (p:Pathogen {species: $species})
            ON CREATE SET
                p.pathogen_id = $pathogen_id,
                p.genus = $genus,
                p.gram_stain = $gram_stain,
                p.pathogen_type = $pathogen_type,
                p.eskape_category = $eskape_category,
                p.aliases = $aliases,
                p.external_ids = $external_ids,
                p.verification_status = 'unreviewed',
                p.created_at = datetime(),
                p.updated_at = datetime()
            ON MATCH SET
                p.updated_at = datetime()
            RETURN p.pathogen_id AS pathogen_id
            """,
            pathogen_id=generate_pathogen_id(),
            species=species,
            genus=genus,
            gram_stain=gram_stain,
            pathogen_type=pathogen_type,
            eskape_category=eskape_category,
            aliases=aliases,
            external_ids=external_ids,
        )
        record = result.single()
        pathogen_id = record["pathogen_id"]

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="Pathogen",
        object_id=pathogen_id,
        actor_id=actor_id,
        delta={"species": species, "pathogen_type": pathogen_type},
        reason=f"获取或创建病原体: {species}",
    )

    return pathogen_id


def get_pathogen_by_species(driver: Driver, species: str) -> Optional[dict]:
    """按物种名查询 Pathogen。"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Pathogen {species: $species})
            RETURN p
            """,
            species=species,
        ).single()
        return dict(result["p"]) if result else None