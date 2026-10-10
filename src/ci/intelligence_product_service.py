# src/ci/intelligence_product_service.py
import uuid
import json
from typing import Optional, Dict, List, Any
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_brief_id() -> str:
    """生成情报简报 ID（格式：CI:BRIEF:XXXXXXXX）"""
    return f"CI:BRIEF:{uuid.uuid4().hex[:8].upper()}"


# ============================================================
# 内部工具：None 安全的 JSON 反序列化
# ============================================================

def _deserialize_brief(data: Dict) -> Dict:
    """对简报的 JSON 字符串字段做 None 安全的反序列化。"""
    defaults = {
        "citations": [],
        "competitive_assessment": {},
        "data_gaps": [],
        "recommended_next_steps": [],
    }
    for k, default in defaults.items():
        v = data.get(k)
        if v is None:
            data[k] = default
        elif isinstance(v, str):
            try:
                data[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                data[k] = default
        # 已是 list/dict 保持原样
    return data


# ============================================================
# 创建
# ============================================================

def create_intelligence_product(
    driver: Driver,
    brief_type: str,
    title: str,
    executive_summary: Any,
    organization_id: Optional[str] = None,
    as_of_date: str = None,
    citations: Optional[List[Dict]] = None,
    competitive_assessment: Optional[Dict] = None,
    data_gaps: Optional[List[str]] = None,
    recommended_next_steps: Optional[List[str]] = None,
    actor_id: str = "system",
) -> str:
    """创建情报产品（简报）节点。"""
    brief_id = generate_brief_id()
    citations = citations or []
    competitive_assessment = competitive_assessment or {}
    data_gaps = data_gaps or []
    recommended_next_steps = recommended_next_steps or []

    citations_json = json.dumps(citations, ensure_ascii=False, default=str)
    assessment_json = json.dumps(competitive_assessment, ensure_ascii=False, default=str)
    gaps_json = json.dumps(data_gaps, ensure_ascii=False, default=str)
    steps_json = json.dumps(recommended_next_steps, ensure_ascii=False, default=str)

    if isinstance(executive_summary, list):
        summary_str = " ".join(str(item) for item in executive_summary)
    else:
        summary_str = str(executive_summary) if executive_summary is not None else ""

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

        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="IntelligenceProduct",
            object_id=brief_id,
            actor_id=actor_id,
            delta={
                "brief_type": brief_type,
                "title": title,
                "organization_id": organization_id,
            },
            reason=f"创建情报产品: {title}",
        )

        return brief_id


# ============================================================
# 查询（消费者接口）
# ============================================================

def get_intelligence_product(driver: Driver, brief_id: str) -> Optional[Dict]:
    """按 ID 查询简报，反序列化 JSON 字段（None 安全）。"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (b:IntelligenceProduct {brief_id: $bid})
            OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
            RETURN b, o.organization_id AS organization_id,
                   o.canonical_name AS organization_name
            """,
            bid=brief_id,
        ).single()
        if not result:
            return None
        data = _deserialize_brief(dict(result["b"]))
        data["organization_id"] = result.get("organization_id")
        data["organization_name"] = result.get("organization_name")
        return data


def get_brief_by_id(driver: Driver, brief_id: str) -> Optional[Dict]:
    """
    消费者接口（契约命名）：按 ID 查询简报。
    等价于 get_intelligence_product。
    """
    return get_intelligence_product(driver, brief_id)


def get_approved_briefs(
    driver: Driver,
    brief_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """
    消费者接口（契约命名）：返回所有 review_status='approved' 的简报。

    Args:
        brief_type: 可选，按 brief_type 过滤（competitor / engineered_phage_technology 等）
        limit: 最多返回条数
    """
    with driver.session() as session:
        if brief_type:
            result = session.run(
                """
                MATCH (b:IntelligenceProduct {review_status: 'approved', brief_type: $bt})
                OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
                RETURN b, o.organization_id AS organization_id,
                       o.canonical_name AS organization_name
                ORDER BY b.created_at DESC
                LIMIT $limit
                """,
                bt=brief_type,
                limit=limit,
            )
        else:
            result = session.run(
                """
                MATCH (b:IntelligenceProduct {review_status: 'approved'})
                OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
                RETURN b, o.organization_id AS organization_id,
                       o.canonical_name AS organization_name
                ORDER BY b.created_at DESC
                LIMIT $limit
                """,
                limit=limit,
            )

        out = []
        for r in result:
            data = _deserialize_brief(dict(r["b"]))
            data["organization_id"] = r.get("organization_id")
            data["organization_name"] = r.get("organization_name")
            out.append(data)
        return out


def get_competitor_programs(driver: Driver, organization_id: str) -> List[Dict]:
    """
    消费者接口（契约命名）：返回某竞争对手的所有研发项目。

    与 build_competitor_profile()['active_programs'] 的字段对齐，
    但只返回项目维度信息，不包含事件/专利/试验。
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
            OPTIONAL MATCH (d)-[:TARGETS_PATHOGEN]->(p:Pathogen)
            WITH d, collect(DISTINCT p.species) AS target_pathogens
            RETURN d.program_id AS program_id,
                   d.canonical_name AS canonical_name,
                   d.development_stage AS development_stage,
                   d.modality AS modality,
                   d.program_type AS program_type,
                   d.program_status AS program_status,
                   d.review_status AS review_status,
                   target_pathogens
            ORDER BY d.canonical_name
            """,
            oid=organization_id,
        )
        return [dict(r) for r in result]


# ============================================================
# 更新
# ============================================================

def update_intelligence_product_review_status(
    driver: Driver,
    brief_id: str,
    new_status: str,
    actor_id: str = "system",
) -> bool:
    """更新简报的审核状态。"""
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

        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="IntelligenceProduct",
            object_id=brief_id,
            actor_id=actor_id,
            delta={"review_status": new_status},
            reason=f"简报审核状态更新为 {new_status}",
        )
        return True