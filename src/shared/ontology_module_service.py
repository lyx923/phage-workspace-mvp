# src/shared/ontology_module_service.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def _generate_module_id() -> str:
    """生成 OntologyModule ID（格式：ONT:XXXXXXXX）"""
    return f"ONT:{uuid.uuid4().hex[:8].upper()}"


def register_ontology_module(
    driver: Driver,
    module_name: str,
    version: str,
    owner_team: str,
    description: Optional[str] = None,
    object_types: Optional[List[str]] = None,
    depends_on: Optional[List[str]] = None,  # 依赖的模块名称列表
    changelog: Optional[str] = None,
    status: str = "experimental",  # active, experimental, deprecated
    actor_id: str = "system",
) -> str:
    """
    注册或更新 OntologyModule 节点（幂等）。
    如果模块名称已存在，则更新其信息（版本、状态等），并记录审计事件。
    
    Args:
        driver: Neo4j 数据库驱动
        module_name: 模块名称（如 "Foundation", "CI_Domain"）
        version: 版本号（如 "0.6.0"）
        owner_team: 负责团队
        description: 模块描述
        object_types: 该模块包含的对象类型列表
        depends_on: 依赖的模块名称列表（如 ["Foundation"]）
        changelog: 更新日志
        status: 状态（active / experimental / deprecated）
        actor_id: 操作者标识
    
    Returns:
        str: 模块 ID（ONT:XXXXXXXX）
    """
    object_types = object_types or []
    depends_on = depends_on or []

    module_id = _generate_module_id()

    with driver.session() as session:
        # 使用 MERGE 确保幂等（按 module_name 查找）
        result = session.run(
            """
            MERGE (m:OntologyModule {module_name: $module_name})
            ON CREATE SET
                m.module_id = $module_id,
                m.version = $version,
                m.owner_team = $owner_team,
                m.description = $description,
                m.object_types = $object_types,
                m.changelog = $changelog,
                m.status = $status,
                m.created_at = datetime(),
                m.updated_at = datetime()
            ON MATCH SET
                m.version = $version,
                m.owner_team = $owner_team,
                m.description = $description,
                m.object_types = $object_types,
                m.changelog = $changelog,
                m.status = $status,
                m.updated_at = datetime()
            RETURN m.module_id AS module_id
            """,
            module_name=module_name,
            module_id=module_id,
            version=version,
            owner_team=owner_team,
            description=description,
            object_types=object_types,
            changelog=changelog,
            status=status,
        )
        record = result.single()
        actual_module_id = record["module_id"]

        # 处理依赖关系
        for dep_name in depends_on:
            session.run(
                """
                MATCH (m:OntologyModule {module_name: $module_name})
                MATCH (d:OntologyModule {module_name: $dep_name})
                MERGE (m)-[:DEPENDS_ON]->(d)
                """,
                module_name=module_name,
                dep_name=dep_name,
            )

        # 写审计日志（CREATE 或 UPDATE，这里统一用 CREATE_OR_UPDATE，但为了符合受控词表，我们使用 CREATE 或 UPDATE 区分）
        # 检查是否为新创建还是更新
        is_new = session.run(
            "MATCH (m:OntologyModule {module_name: $module_name}) WHERE m.created_at = m.updated_at RETURN m",
            module_name=module_name
        ).single() is not None  # 如果创建时间等于更新时间，说明是新创建的

        action_type = "CREATE" if is_new else "UPDATE"
        write_audit_event(
            driver,
            action_type=action_type,
            object_type="OntologyModule",
            object_id=actual_module_id,
            actor_id=actor_id,
            delta={
                "module_name": module_name,
                "version": version,
                "status": status,
                "depends_on": depends_on,
            },
            reason=f"{'注册' if is_new else '更新'} OntologyModule: {module_name} v{version}",
        )

        return actual_module_id


def get_module_registry(driver: Driver) -> List[Dict]:
    """
    返回当前所有已注册的 OntologyModule 及其依赖关系。
    
    Returns:
        List[Dict]: 每个模块包含 module_name, version, status, owner_team, depends_on 等
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (m:OntologyModule)
            OPTIONAL MATCH (m)-[:DEPENDS_ON]->(dep:OntologyModule)
            RETURN m.module_name AS module_name,
                   m.version AS version,
                   m.status AS status,
                   m.owner_team AS owner_team,
                   m.description AS description,
                   m.object_types AS object_types,
                   m.changelog AS changelog,
                   m.created_at AS created_at,
                   m.updated_at AS updated_at,
                   collect(dep.module_name) AS depends_on
            ORDER BY m.module_name
            """
        )
        return [dict(record) for record in result]