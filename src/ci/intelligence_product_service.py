# src/ci/intelligence_product_service.py
import uuid
import json
from typing import Optional, Dict, List, Any
from neo4j import Driver
from src.foundation.audit_service import log_action


def generate_brief_id() -> str:
    return f"CI:BRIEF:{uuid.uuid4().hex[:8].upper()}"


def create_intelligence_product(
    driver: Driver,
    brief_type: str,
    title: str,
    executive_summary: Any,  # 可以是字符串或列表，但最终存为字符串
    organization_id: Optional[str] = None,
    as_of_date: str = None,
    citations: Optional[List[Dict]] = None,
    competitive_assessment: Optional[Dict] = None,
    data_gaps: Optional[List[str]] = None,
    recommended_next_steps: Optional[List[str]] = None,
    actor_id: str = "system",
) -> str:
    """
    创建 IntelligenceProduct 节点，将复杂对象序列化为 JSON 字符串存储。
    """
    brief_id = generate_brief_id()
    citations = citations or []
    competitive_assessment = competitive_assessment or {}
    data_gaps = data_gaps or []
    recommended_next_steps = recommended_next_steps or []

    # 将复杂对象转为 JSON 字符串（确保是字符串格式）
    citations_json = json.dumps(citations, ensure_ascii=False)
    assessment_json = json.dumps(competitive_assessment, ensure_ascii=False)
    gaps_json = json.dumps(data_gaps, ensure_ascii=False)
    steps_json = json.dumps(recommended_next_steps, ensure_ascii=False)
    
    # executive_summary 如果是列表，转为字符串
    if isinstance(executive_summary, list):
        summary_str = " ".join(str(item) for item in executive_summary)
    else:
        summary_str = str(executive_summary)

    with driver.session() as session:
        session.run(
            """
            CREATE (b:IntelligenceProduct {
                brief_id: $brief_id,
                brief_type: $brief_type,
                title: $title,
                executive_summary: $summary,
                organization_id: $org_id,
                as_of_date: $as_of_date,
                citations: $citations_json,
                competitive_assessment: $assessment_json,
                data_gaps: $gaps_json,
                recommended_next_steps: $steps_json,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
            """,
            brief_id=brief_id,
            brief_type=brief_type,
            title=title,
            summary=summary_str,
            org_id=organization_id,
            as_of_date=as_of_date,
            citations_json=citations_json,
            assessment_json=assessment_json,
            gaps_json=gaps_json,
            steps_json=steps_json,
        )

        if organization_id:
            session.run(
                """
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                MATCH (o:Organization {organization_id: $oid})
                CREATE (b)-[:COVERS]->(o)
                """,
                bid=brief_id,
                oid=organization_id,
            )

        log_action(
            driver,
            domain="ci",
            action_type="CREATE_INTELLIGENCE_PRODUCT",
            object_type="IntelligenceProduct",
            object_id=brief_id,
            actor_id=actor_id,
            after_snapshot={
                "brief_type": brief_type,
                "title": title,
                "organization_id": organization_id,
            },
            reason=f"创建情报产品: {title}",
        )

        return brief_id


def get_intelligence_product(driver: Driver, brief_id: str) -> Optional[Dict]:
    """查询简报，自动反序列化 JSON 字段"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (b:IntelligenceProduct {brief_id: $bid})
            OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
            RETURN b, o.organization_id AS organization_id, o.canonical_name AS organization_name
            """,
            bid=brief_id,
        ).single()
        if not result:
            return None
        data = dict(result["b"])
        # 反序列化 JSON 字段
        data["citations"] = json.loads(data.get("citations", "[]"))
        data["competitive_assessment"] = json.loads(data.get("competitive_assessment", "{}"))
        data["data_gaps"] = json.loads(data.get("data_gaps", "[]"))
        data["recommended_next_steps"] = json.loads(data.get("recommended_next_steps", "[]"))
        data["organization_id"] = result.get("organization_id")
        data["organization_name"] = result.get("organization_name")
        return data


def update_intelligence_product_review_status(
    driver: Driver,
    brief_id: str,
    new_status: str,
    actor_id: str = "system",
) -> bool:
    valid_statuses = ["pending", "approved", "rejected"]
    if new_status not in valid_statuses:
        raise ValueError(f"状态必须是 {valid_statuses} 之一")

    with driver.session() as session:
        check = session.run(
            "MATCH (b:IntelligenceProduct {brief_id: $bid}) RETURN b",
            bid=brief_id,
        ).single()
        if not check:
            raise ValueError(f"简报 {brief_id} 不存在")

        session.run(
            """
            MATCH (b:IntelligenceProduct {brief_id: $bid})
            SET b.review_status = $status, b.updated_at = datetime()
            """,
            bid=brief_id,
            status=new_status,
        )

        log_action(
            driver,
            domain="ci",
            action_type="UPDATE_BRIEF_REVIEW_STATUS",
            object_type="IntelligenceProduct",
            object_id=brief_id,
            actor_id=actor_id,
            after_snapshot={"review_status": new_status},
        )
        return True