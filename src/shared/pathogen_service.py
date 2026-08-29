# src/shared/pathogen_service.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.foundation.audit_service import log_action


def generate_pathogen_id() -> str:
    """生成格式为 PATH-XXXXXXXX 的 Pathogen ID"""
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
    获取或创建 Pathogen 节点，按 species 去重 (MERGE 语义)。
    跨域共享核心：Scientific Domain 和 CI Domain 通过此函数共享同一个 Pathogen 节点。
    重复调用同一 species 返回已有的 pathogen_id。
    自动记录审计事件 (CREATE，仅当新创建时)。
    """
    aliases = aliases or []
    # 如果 external_ids 是空字典或 None，设为 None（Cypher 会存为 null）
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

    log_action(
        driver,
        domain="foundation",
        action_type="CREATE_OR_GET",
        object_type="Pathogen",
        object_id=pathogen_id,
        actor_id=actor_id,
        after_snapshot={"species": species, "pathogen_type": pathogen_type},
        reason=f"获取或创建病原体: {species}",
    )

    return pathogen_id


def get_pathogen_by_species(driver: Driver, species: str) -> Optional[dict]:
    """根据 species 查询已有 Pathogen"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Pathogen {species: $species})
            RETURN p
            """,
            species=species,
        ).single()
        return dict(result["p"]) if result else None