# src/engineering_intelligence/result_extractor.py
"""
TechnicalResult 相关（PRD 9.5 / 13.6）

职责：
    - 创建技术结果（TechnicalResult）
    - 建立与构建体（RESULT_FOR）、来源（REPORTED_IN）、主张（SUPPORTED_OR_CHALLENGES）的关系
    - 回填历史关系
    - 查询结果与判定

边界：
    - 只把 outcome_direction 映射到 SUPPORTED / CHALLENGES，不做真伪判断
"""

import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_result_id() -> str:
    """生成技术结果 ID（格式：ENG:RESULT:XXXXXXXX）。"""
    return f"ENG:RESULT:{uuid.uuid4().hex[:8].upper()}"


def _direction_to_relation(outcome_direction: Optional[str]) -> Optional[str]:
    """
    内部：把 outcome_direction 映射到关系类型。

    positive  → SUPPORTED（支持主张）
    negative  → CHALLENGES（挑战主张）
    其他      → None（不建立关系）
    """
    if outcome_direction == "positive":
        return "SUPPORTED"
    if outcome_direction == "negative":
        return "CHALLENGES"
    return None


def create_technical_result(
    driver: Driver, result_type: str, study_context: str,
    outcome_direction: Optional[str] = None,
    metric_name: Optional[str] = None,
    metric_value: Optional[float] = None,
    metric_unit: Optional[str] = None,
    comparator: Optional[str] = None,
    sample_size: Optional[int] = None,
    limitation_summary: Optional[str] = None,
    reproducibility_status: str = "single_source",
    construct_id: Optional[str] = None,
    source_id: Optional[str] = None,
    claim_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    创建技术结果。

    可选：
        - (结果)-[:RESULT_FOR]->(构建体)
        - (结果)-[:REPORTED_IN]->(来源)
        - (结果)-[SUPPORTED_OR_CHALLENGES]->(主张)（仅当 outcome_direction 为 positive/negative）

    Args:
        result_type: 结果类型
        study_context: 研究上下文（in_vitro / animal / clinical / computational）
        outcome_direction: 结果方向（positive / negative / mixed / neutral）
        metric_name / metric_value / metric_unit: 指标
        comparator / sample_size / limitation_summary: 对照 / 样本量 / 局限
        reproducibility_status: 复现状态（默认 single_source）
        construct_id / source_id / claim_id: 关联对象
        actor_id: 操作者

    Returns:
        str: result_id
    """
    result_id = generate_result_id()

    with driver.session() as session:
        # 创建结果节点
        session.run("""
            CREATE (tr:TechnicalResult {
                result_id: $result_id, result_type: $result_type,
                study_context: $study_context,
                outcome_direction: $outcome_direction,
                metric_name: $metric_name, metric_value: $metric_value,
                metric_unit: $metric_unit, comparator: $comparator,
                sample_size: $sample_size,
                limitation_summary: $limitation_summary,
                reproducibility_status: $reproducibility_status,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
        """, result_id=result_id, result_type=result_type,
             study_context=study_context, outcome_direction=outcome_direction,
             metric_name=metric_name, metric_value=metric_value,
             metric_unit=metric_unit, comparator=comparator,
             sample_size=sample_size, limitation_summary=limitation_summary,
             reproducibility_status=reproducibility_status)

        # RESULT_FOR 构建体
        if construct_id:
            session.run("""
                MATCH (tr:TechnicalResult {result_id: $result_id})
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MERGE (tr)-[:RESULT_FOR]->(ec)
            """, result_id=result_id, construct_id=construct_id)

        # REPORTED_IN 来源
        if source_id:
            session.run("""
                MATCH (tr:TechnicalResult {result_id: $result_id})
                MATCH (s:SourceArtifact {source_id: $source_id})
                MERGE (tr)-[:REPORTED_IN]->(s)
            """, result_id=result_id, source_id=source_id)

        # SUPPORTED_OR_CHALLENGES 主张
        linked_claim = False
        verdict = None
        if claim_id:
            verdict = _direction_to_relation(outcome_direction)
            if verdict:
                tc_chk = session.run(
                    "MATCH (tc:TechnicalClaim {claim_id: $cid}) RETURN tc LIMIT 1",
                    cid=claim_id,
                ).single()
                if tc_chk:
                    session.run("""
                        MATCH (tr:TechnicalResult {result_id: $rid})
                        MATCH (tc:TechnicalClaim {claim_id: $cid})
                        MERGE (tr)-[r:SUPPORTED_OR_CHALLENGES]->(tc)
                        SET r.verdict = $verdict,
                            r.created_at = COALESCE(r.created_at, datetime())
                    """, rid=result_id, cid=claim_id, verdict=verdict)
                    linked_claim = True
                else:
                    print(f"⚠️ TechnicalClaim {claim_id} 不存在，跳过 SUPPORTED_OR_CHALLENGES")
            else:
                print(
                    f"ℹ️ outcome_direction={outcome_direction!r} 无法判定 SUPPORTED/CHALLENGES，"
                    f"跳过关系建立"
                )

        write_audit_event(
            driver, action_type="CREATE",
            object_type="TechnicalResult", object_id=result_id,
            actor_id=actor_id,
            delta={"result_type": result_type, "study_context": study_context,
                   "outcome_direction": outcome_direction, "claim_id": claim_id,
                   "verdict": verdict, "linked_claim": linked_claim},
            reason=f"创建技术结果: {result_type}",
        )
        return result_id


def link_result_to_claim(driver, result_id, claim_id, actor_id="system"):
    """
    手工建立 (结果)-[:SUPPORTED_OR_CHALLENGES]->(主张) 关系。

    根据结果的 outcome_direction 自动判定 SUPPORTED / CHALLENGES；
    若 direction 非 positive/negative，抛异常。
    """
    with driver.session() as s:
        tr = s.run("""
            MATCH (tr:TechnicalResult {result_id: $rid})
            RETURN tr.outcome_direction AS od LIMIT 1
        """, rid=result_id).single()
        if not tr:
            raise ValueError(f"TechnicalResult {result_id} 不存在")
        tc = s.run("MATCH (tc:TechnicalClaim {claim_id: $cid}) RETURN tc LIMIT 1",
                   cid=claim_id).single()
        if not tc:
            raise ValueError(f"TechnicalClaim {claim_id} 不存在")
        verdict = _direction_to_relation(tr["od"])
        if not verdict:
            raise ValueError(
                f"result {result_id} 的 outcome_direction={tr['od']!r} "
                f"无法判定 SUPPORTED/CHALLENGES"
            )
        s.run("""
            MATCH (tr:TechnicalResult {result_id: $rid})
            MATCH (tc:TechnicalClaim {claim_id: $cid})
            MERGE (tr)-[r:SUPPORTED_OR_CHALLENGES]->(tc)
            SET r.verdict = $verdict,
                r.created_at = COALESCE(r.created_at, datetime())
        """, rid=result_id, cid=claim_id, verdict=verdict)

    write_audit_event(
        driver, action_type="LINK_CREATE",
        object_type="TechnicalResult", object_id=result_id,
        actor_id=actor_id,
        delta={"relation": "SUPPORTED_OR_CHALLENGES",
               "claim_id": claim_id, "verdict": verdict},
        reason=f"结果 {result_id} {verdict} 主张 {claim_id}",
    )
    return True


def backfill_result_to_claim(driver, actor_id="backfill"):
    """
    回填 SUPPORTED_OR_CHALLENGES 关系：
    从 (结果)-RESULT_FOR->(构建体)<-CLAIMS_ABOUT-(主张) 推导，
    要求 result_type == claim_type 且 outcome_direction 为 positive/negative。
    """
    created = 0
    details = []
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
                  <-[:CLAIMS_ABOUT]-(tc:TechnicalClaim)
            WHERE tr.result_type = tc.claim_type
              AND tr.outcome_direction IN ['positive', 'negative']
              AND NOT (tr)-[:SUPPORTED_OR_CHALLENGES]->(tc)
            RETURN tr.result_id AS rid, tr.outcome_direction AS od,
                   tc.claim_id AS cid, ec.construct_id AS ecid
        """))
        for r in rows:
            verdict = "SUPPORTED" if r["od"] == "positive" else "CHALLENGES"
            s.run("""
                MATCH (tr:TechnicalResult {result_id: $rid})
                MATCH (tc:TechnicalClaim {claim_id: $cid})
                MERGE (tr)-[rel:SUPPORTED_OR_CHALLENGES]->(tc)
                SET rel.verdict = $verdict,
                    rel.created_at = COALESCE(rel.created_at, datetime())
            """, rid=r["rid"], cid=r["cid"], verdict=verdict)
            created += 1
            details.append({"result_id": r["rid"], "claim_id": r["cid"],
                            "construct_id": r["ecid"], "verdict": verdict})

    if created > 0:
        write_audit_event(
            driver, action_type="LINK_CREATE",
            object_type="TechnicalResult", object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_supported_or_challenges": created, "details": details},
            reason=f"回填 SUPPORTED_OR_CHALLENGES 关系：{created} 条",
        )
    return {"created": created, "details": details}


def get_results_by_construct(driver, construct_id):
    """查询某构建体的所有技术结果，附带来源。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tr)-[:REPORTED_IN]->(s:SourceArtifact)
            RETURN tr.result_id AS id, tr.result_type AS result_type,
                   tr.study_context AS study_context,
                   tr.outcome_direction AS outcome_direction,
                   tr.metric_name AS metric_name,
                   tr.metric_value AS metric_value,
                   tr.metric_unit AS metric_unit,
                   tr.sample_size AS sample_size,
                   tr.limitation_summary AS limitation_summary,
                   tr.reproducibility_status AS reproducibility_status,
                   s.source_id AS source_id, s.title AS source_title
            ORDER BY tr.created_at DESC
        """, construct_id=construct_id)
        return [dict(record) for record in result]


def get_verdicts_for_claim(driver, claim_id):
    """查询某主张的所有 SUPPORTED_OR_CHALLENGES 判定。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (tr:TechnicalResult)-[r:SUPPORTED_OR_CHALLENGES]->(tc:TechnicalClaim {claim_id: $cid})
            RETURN tr.result_id AS result_id, tr.result_type AS result_type,
                   tr.outcome_direction AS outcome_direction,
                   r.verdict AS verdict, r.created_at AS created_at
            ORDER BY r.created_at DESC
        """, cid=claim_id)
        return [dict(record) for record in result]