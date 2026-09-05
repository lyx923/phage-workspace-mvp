# src/shared/pathogen_service.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from shared.audit_service import write_audit_event


def generate_pathogen_id() -> str:
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
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Pathogen {species: $species})
            RETURN p
            """,
            species=species,
        ).single()
        return dict(result["p"]) if result else None