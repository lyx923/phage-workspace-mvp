# src/ci/product_asset_service.py
"""
ProductAsset 服务（PRD 5.2）

关系：
    (Organization)-[:OWNS_ASSET]->(ProductAsset)
    (ProductAsset)-[:BASED_ON]->(DevelopmentProgram)   [可选]
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


ASSET_TYPES = {"drug", "diagnostic", "platform", "software", "service", "other"}
ASSET_STATUSES = {"discovery", "preclinical", "clinical", "approved", "commercial", "discontinued", "unknown"}


def generate_asset_id() -> str:
    return f"CI:ASSET:{uuid.uuid4().hex[:8].upper()}"


def create_product_asset(
    driver: Driver,
    name: str,
    organization_id: str,
    asset_type: str = "drug",
    status: str = "unknown",
    based_on_program_id: Optional[str] = None,
    description: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """创建 ProductAsset。按 name + organization_id 去重。"""
    if not name or not name.strip():
        raise ValueError("name 不能为空")
    name = name.strip()

    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type 必须是 {sorted(ASSET_TYPES)} 之一")
    if status not in ASSET_STATUSES:
        raise ValueError(f"status 必须是 {sorted(ASSET_STATUSES)} 之一")

    with driver.session() as s:
        org_ok = s.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.canonical_name AS n LIMIT 1
        """, oid=organization_id).single()
        if not org_ok:
            raise ValueError(f"Organization {organization_id} 不存在")

        existing = s.run("""
            MATCH (o:Organization {organization_id: $oid})-[:OWNS_ASSET]->(a:ProductAsset)
            WHERE toLower(a.name) = toLower($name)
            RETURN a.asset_id AS aid LIMIT 1
        """, oid=organization_id, name=name).single()
        if existing:
            return existing["aid"]

        asset_id = generate_asset_id()
        s.run("""
            MATCH (o:Organization {organization_id: $oid})
            CREATE (a:ProductAsset {
                asset_id: $aid,
                name: $name,
                asset_type: $atype,
                status: $status,
                description: $desc,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
            CREATE (o)-[:OWNS_ASSET]->(a)
        """, oid=organization_id, aid=asset_id, name=name,
             atype=asset_type, status=status, desc=description)

        if based_on_program_id:
            s.run("""
                MATCH (a:ProductAsset {asset_id: $aid})
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MERGE (a)-[:BASED_ON]->(d)
            """, aid=asset_id, pid=based_on_program_id)

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="ProductAsset",
        object_id=asset_id,
        actor_id=actor_id,
        delta={"name": name, "organization_id": organization_id, "asset_type": asset_type},
        reason=f"创建产品资产: {name}",
    )
    return asset_id


def list_product_assets(
    driver: Driver,
    organization_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    with driver.session() as s:
        if organization_id:
            rows = list(s.run("""
                MATCH (o:Organization {organization_id: $oid})-[:OWNS_ASSET]->(a:ProductAsset)
                OPTIONAL MATCH (a)-[:BASED_ON]->(d:DevelopmentProgram)
                RETURN a.asset_id AS asset_id, a.name AS name,
                       a.asset_type AS asset_type, a.status AS status,
                       o.canonical_name AS organization,
                       collect(DISTINCT d.canonical_name) AS programs
                ORDER BY a.name LIMIT $limit
            """, oid=organization_id, limit=limit))
        else:
            rows = list(s.run("""
                MATCH (o:Organization)-[:OWNS_ASSET]->(a:ProductAsset)
                OPTIONAL MATCH (a)-[:BASED_ON]->(d:DevelopmentProgram)
                RETURN a.asset_id AS asset_id, a.name AS name,
                       a.asset_type AS asset_type, a.status AS status,
                       o.canonical_name AS organization,
                       collect(DISTINCT d.canonical_name) AS programs
                ORDER BY a.name LIMIT $limit
            """, limit=limit))
    return [dict(r) for r in rows]