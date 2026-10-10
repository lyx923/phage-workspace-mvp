# src/decision_support/decision_brief.py
"""
DecisionBrief 服务（PRD 10.2）

DecisionBrief 表示围绕一个 IntelligenceQuestion 形成的决策辅助简报。
它是 Decision Layer 的核心对象。

与 IntelligenceProduct 的区别：
- IntelligenceProduct：情报载体（事实层），用于 competitor/technology brief
- DecisionBrief：面向决策的辅助简报，用于形成 DecisionRecord

关系：
    (DecisionBrief)-[:ANSWERS]->(IntelligenceQuestion)
    (DecisionBrief)-[:USES_EVENT]->(IntelligenceEvent)
    (DecisionBrief)-[:USES_CLAIM]->(TechnicalClaim)
    (DecisionBrief)-[:USES_RESULT]->(TechnicalResult)
    (DecisionBrief)-[:CITES]->(SourceArtifact)
    (DecisionBrief)-[:INCLUDES_ASSESSMENT]->(CompetitorAssessment)
    (DecisionBrief)-[:INCLUDES_ASSESSMENT]->(TechnologyAssessment)
    (DecisionBrief)-[:DERIVED_FROM]->(IntelligenceProduct)   可选

边界：
- 不自动生成 approved Review
- 不自动判断事实真伪
- 所有引用关系必须可追溯
- generated_by 明确区分 analyst / deepseek_assisted / system
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


BRIEF_TYPES = {"competitor", "technology", "landscape", "alert"}
GENERATED_BY = {"analyst", "deepseek_assisted", "system"}


def generate_decision_brief_id() -> str:
    """生成 DecisionBrief ID（格式：CI:DBRIEF:XXXXXXXX）"""
    return f"CI:DBRIEF:{uuid.uuid4().hex[:8].upper()}"


def _to_json_field(v: Any) -> Optional[str]:
    """把 dict / list 转 JSON 字符串；字符串原样返回；None 返回 None。"""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        return str(v)


# ============================================================
# 创建 DecisionBrief
# ============================================================

def create_decision_brief(
    driver: Driver,
    brief_type: str,
    title: str,
    executive_summary: str,
    key_facts: Optional[List[Dict]] = None,
    assessments: Optional[List[Dict]] = None,
    uncertainties: Optional[List[str]] = None,
    options: Optional[List[Dict]] = None,
    recommended_next_steps: Optional[List[str]] = None,
    generated_by: str = "analyst",
    model_used: Optional[str] = None,
    as_of_date: Optional[str] = None,
    # ---- 关联关系（全部可选）----
    question_id: Optional[str] = None,
    event_ids: Optional[List[str]] = None,
    claim_ids: Optional[List[str]] = None,
    result_ids: Optional[List[str]] = None,
    source_ids: Optional[List[str]] = None,
    competitor_assessment_ids: Optional[List[str]] = None,
    technology_assessment_ids: Optional[List[str]] = None,
    derived_from_product_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    创建 DecisionBrief 节点，并建立所有引用的关系。

    Args:
        driver: Neo4j 驱动
        brief_type: competitor / technology / landscape / alert
        title: 标题
        executive_summary: 执行摘要
        key_facts: 关键事实列表（每个元素建议 {"text": "...", "source_object_id": "..."}）
        assessments: 内部分析判断列表（{"type": "competitor/technology", "assessment_id": "..."}）
        uncertainties: 不确定项列表
        options: 决策选项列表（{"option_type": "...", "summary": "..."}）
        recommended_next_steps: 建议下一步
        generated_by: analyst / deepseek_assisted / system
        model_used: 若由 LLM 辅助，填模型版本
        as_of_date: 信息截止日期（YYYY-MM-DD）
        question_id: 关联的 IntelligenceQuestion
        event_ids: 引用的 IntelligenceEvent IDs
        claim_ids: 引用的 TechnicalClaim IDs
        result_ids: 引用的 TechnicalResult IDs
        source_ids: 引用的 SourceArtifact IDs
        competitor_assessment_ids: 包含的 CompetitorAssessment IDs
        technology_assessment_ids: 包含的 TechnologyAssessment IDs
        derived_from_product_id: 可选，从哪个 IntelligenceProduct 派生
        actor_id: 操作者

    Returns:
        str: brief_id（CI:DBRIEF:XXXXXXXX）

    Raises:
        ValueError: brief_type / generated_by 非法，或关联对象不存在
    """
    if brief_type not in BRIEF_TYPES:
        raise ValueError(f"brief_type 必须是 {sorted(BRIEF_TYPES)} 之一")
    if generated_by not in GENERATED_BY:
        raise ValueError(f"generated_by 必须是 {sorted(GENERATED_BY)} 之一")
    if not title or not title.strip():
        raise ValueError("title 不能为空")

    key_facts = key_facts or []
    assessments = assessments or []
    uncertainties = uncertainties or []
    options = options or []
    recommended_next_steps = recommended_next_steps or []
    event_ids = event_ids or []
    claim_ids = claim_ids or []
    result_ids = result_ids or []
    source_ids = source_ids or []
    competitor_assessment_ids = competitor_assessment_ids or []
    technology_assessment_ids = technology_assessment_ids or []

    brief_id = generate_decision_brief_id()
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")

    with driver.session() as session:
        # 1. 创建节点
        session.run(
            """
            CREATE (b:DecisionBrief {
                brief_id: $brief_id,
                brief_type: $brief_type,
                title: $title,
                executive_summary: $executive_summary,
                key_facts: $key_facts,
                assessments: $assessments,
                uncertainties: $uncertainties,
                options: $options,
                recommended_next_steps: $recommended_next_steps,
                generated_by: $generated_by,
                model_used: $model_used,
                as_of_date: $as_of_date,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
            """,
            brief_id=brief_id,
            brief_type=brief_type,
            title=title.strip(),
            executive_summary=executive_summary or "",
            key_facts=_to_json_field(key_facts),
            assessments=_to_json_field(assessments),
            uncertainties=uncertainties,
            options=_to_json_field(options),
            recommended_next_steps=recommended_next_steps,
            generated_by=generated_by,
            model_used=model_used,
            as_of_date=as_of_date,
        )

        # 2. ANSWERS → IntelligenceQuestion
        if question_id:
            chk = session.run(
                "MATCH (iq:IntelligenceQuestion {question_id: $qid}) RETURN iq LIMIT 1",
                qid=question_id,
            ).single()
            if not chk:
                raise ValueError(f"IntelligenceQuestion {question_id} 不存在")
            session.run(
                """
                MATCH (b:DecisionBrief {brief_id: $bid})
                MATCH (iq:IntelligenceQuestion {question_id: $qid})
                CREATE (b)-[:ANSWERS]->(iq)
                SET iq.updated_at = datetime()
                """,
                bid=brief_id,
                qid=question_id,
            )

        # 3. USES_EVENT → IntelligenceEvent
        for eid in event_ids:
            chk = session.run(
                "MATCH (e:IntelligenceEvent {event_id: $eid}) RETURN e LIMIT 1",
                eid=eid,
            ).single()
            if not chk:
                print(f"⚠️ IntelligenceEvent {eid} 不存在，跳过 USES_EVENT")
                continue
            session.run(
                """
                MATCH (b:DecisionBrief {brief_id: $bid})
                MATCH (e:IntelligenceEvent {event_id: $eid})
                CREATE (b)-[:USES_EVENT]->(e)
                """,
                bid=brief_id,
                eid=eid,
            )

        # 4. USES_CLAIM → TechnicalClaim
        for cid in claim_ids:
            chk = session.run(
                "MATCH (c:TechnicalClaim {claim_id: $cid}) RETURN c LIMIT 1",
                cid=cid,
            ).single()
            if not chk:
                print(f"⚠️ TechnicalClaim {cid} 不存在，跳过 USES_CLAIM")
                continue
            session.run(
                """
                MATCH (b:DecisionBrief {brief_id: $bid})
                MATCH (c:TechnicalClaim {claim_id: $cid})
                CREATE (b)-[:USES_CLAIM]->(c)
                """,
                bid=brief_id,
                cid=cid,
            )

        # 5. USES_RESULT → TechnicalResult
        for rid in result_ids:
            chk = session.run(
                "MATCH (r:TechnicalResult {result_id: $rid}) RETURN r LIMIT 1",
                rid=rid,
            ).single()
            if not chk:
                print(f"⚠️ TechnicalResult {rid} 不存在，跳过 USES_RESULT")
                continue
            session.run(
                """
                MATCH (b:DecisionBrief {brief_id: $bid})
                MATCH (r:TechnicalResult {result_id: $rid})
                CREATE (b)-[:USES_RESULT]->(r)
                """,
                bid=brief_id,
                rid=rid,
            )

        # 6. CITES → SourceArtifact
        for sid in source_ids:
            chk = session.run(
                "MATCH (s:SourceArtifact {source_id: $sid}) RETURN s LIMIT 1",
                sid=sid,
            ).single()
            if not chk:
                print(f"⚠️ SourceArtifact {sid} 不存在，跳过 CITES")
                continue
            session.run(
                """
                MATCH (b:DecisionBrief {brief_id: $bid})
                MATCH (s:SourceArtifact {source_id: $sid})
                CREATE (b)-[:CITES]->(s)
                """,
                bid=brief_id,
                sid=sid,
            )

        # 7. INCLUDES_ASSESSMENT → CompetitorAssessment
        for aid in competitor_assessment_ids:
            chk = session.run(
                "MATCH (ca:CompetitorAssessment {assessment_id: $aid}) RETURN ca LIMIT 1",
                aid=aid,
            ).single()
            if not chk:
                print(f"⚠️ CompetitorAssessment {aid} 不存在，跳过 INCLUDES_ASSESSMENT")
                continue
            session.run(
                """
                MATCH (b:DecisionBrief {brief_id: $bid})
                MATCH (ca:CompetitorAssessment {assessment_id: $aid})
                CREATE (b)-[:INCLUDES_ASSESSMENT]->(ca)
                """,
                bid=brief_id,
                aid=aid,
            )

        # 8. INCLUDES_ASSESSMENT → TechnologyAssessment
        for aid in technology_assessment_ids:
            chk = session.run(
                "MATCH (ta:TechnologyAssessment {technology_assessment_id: $aid}) RETURN ta LIMIT 1",
                aid=aid,
            ).single()
            if not chk:
                print(f"⚠️ TechnologyAssessment {aid} 不存在，跳过 INCLUDES_ASSESSMENT")
                continue
            session.run(
                """
                MATCH (b:DecisionBrief {brief_id: $bid})
                MATCH (ta:TechnologyAssessment {technology_assessment_id: $aid})
                CREATE (b)-[:INCLUDES_ASSESSMENT]->(ta)
                """,
                bid=brief_id,
                aid=aid,
            )

        # 9. DERIVED_FROM → IntelligenceProduct（可选）
        if derived_from_product_id:
            chk = session.run(
                """
                MATCH (p:IntelligenceProduct {brief_id: $pid})
                RETURN p LIMIT 1
                """,
                pid=derived_from_product_id,
            ).single()
            if chk:
                session.run(
                    """
                    MATCH (b:DecisionBrief {brief_id: $bid})
                    MATCH (p:IntelligenceProduct {brief_id: $pid})
                    CREATE (b)-[:DERIVED_FROM]->(p)
                    """,
                    bid=brief_id,
                    pid=derived_from_product_id,
                )

    # 10. 审计
    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="DecisionBrief",
        object_id=brief_id,
        actor_id=actor_id,
        delta={
            "brief_type": brief_type,
            "title": title,
            "generated_by": generated_by,
            "question_id": question_id,
            "event_ids": event_ids,
            "claim_ids": claim_ids,
            "result_ids": result_ids,
            "source_ids": source_ids,
            "competitor_assessment_ids": competitor_assessment_ids,
            "technology_assessment_ids": technology_assessment_ids,
        },
        reason=f"创建决策简报: {title[:60]}",
    )

    return brief_id


# ============================================================
# 查询
# ============================================================

def get_decision_brief(driver: Driver, brief_id: str) -> Optional[Dict]:
    """按 ID 查询 DecisionBrief，反序列化 JSON 字段。"""
    with driver.session() as session:
        r = session.run(
            """
            MATCH (b:DecisionBrief {brief_id: $bid})
            OPTIONAL MATCH (b)-[:ANSWERS]->(iq:IntelligenceQuestion)
            RETURN b, iq.question_id AS question_id
            """,
            bid=brief_id,
        ).single()
        if not r:
            return None
        data = dict(r["b"])
        for k in ("key_facts", "assessments", "options"):
            v = data.get(k)
            if isinstance(v, str):
                try:
                    data[k] = json.loads(v)
                except Exception:
                    pass
        data["question_id"] = r.get("question_id")
        return data


def update_decision_brief_review_status(
    driver: Driver,
    brief_id: str,
    new_status: str,
    actor_id: str = "system",
) -> bool:
    """更新 DecisionBrief 的 review_status。"""
    valid = ["pending", "reviewed", "approved", "rejected"]
    if new_status not in valid:
        raise ValueError(f"状态必须是 {valid} 之一")

    with driver.session() as session:
        chk = session.run(
            "MATCH (b:DecisionBrief {brief_id: $bid}) RETURN b",
            bid=brief_id,
        ).single()
        if not chk:
            raise ValueError(f"DecisionBrief {brief_id} 不存在")

        session.run(
            """
            MATCH (b:DecisionBrief {brief_id: $bid})
            SET b.review_status = $status,
                b.updated_at = datetime()
            """,
            bid=brief_id,
            status=new_status,
        )

    write_audit_event(
        driver,
        action_type="STATUS_CHANGE",
        object_type="DecisionBrief",
        object_id=brief_id,
        actor_id=actor_id,
        delta={"review_status": {"after": new_status}},
        reason=f"DecisionBrief 审核状态更新为 {new_status}",
    )
    return True


# ============================================================
# 便捷入口：从 CompetitorBrief 派生出 DecisionBrief 草稿
# ============================================================

def create_decision_brief_from_competitor_brief(
    driver: Driver,
    competitor_brief_id: str,
    question_id: Optional[str] = None,
    generated_by: str = "analyst",
    actor_id: str = "system",
) -> str:
    """
    从已有的 CompetitorBrief（IntelligenceProduct）派生一份 DecisionBrief 草稿。

    - brief_type = "competitor"
    - DERIVED_FROM → IntelligenceProduct
    - 自动提取 citations → CITES → SourceArtifact
    """
    with driver.session() as session:
        r = session.run(
            """
            MATCH (p:IntelligenceProduct {brief_id: $pid})
            RETURN p.brief_id AS brief_id,
                   p.title AS title,
                   p.executive_summary AS summary,
                   p.competitive_assessment AS ca,
                   p.recommended_next_steps AS steps,
                   p.citations AS citations,
                   p.as_of_date AS as_of_date
            """,
            pid=competitor_brief_id,
        ).single()
        if not r:
            raise ValueError(f"IntelligenceProduct {competitor_brief_id} 不存在")

    # 解析 JSON 字段
    try:
        ca = json.loads(r["ca"]) if isinstance(r["ca"], str) else (r["ca"] or {})
    except Exception:
        ca = {}
    try:
        steps = json.loads(r["steps"]) if isinstance(r["steps"], str) else (r["steps"] or [])
    except Exception:
        steps = []
    try:
        citations = json.loads(r["citations"]) if isinstance(r["citations"], str) else (r["citations"] or [])
    except Exception:
        citations = []

    source_ids = [c.get("source_id") for c in citations if c.get("source_id")]

    # 从 competitive_assessment 里提取 uncertainties
    uncertainties = []
    for u in ca.get("uncertainties", []) or []:
        txt = u.get("signal_text") if isinstance(u, dict) else str(u)
        if txt:
            uncertainties.append(txt)

    return create_decision_brief(
        driver,
        brief_type="competitor",
        title=f"决策简报 - {r['title'] or competitor_brief_id}",
        executive_summary=r["summary"] or "",
        key_facts=ca.get("threats", []) or [],
        assessments=ca,
        uncertainties=uncertainties,
        options=[],
        recommended_next_steps=steps,
        generated_by=generated_by,
        as_of_date=r["as_of_date"],
        question_id=question_id,
        source_ids=source_ids,
        derived_from_product_id=competitor_brief_id,
        actor_id=actor_id,
    )