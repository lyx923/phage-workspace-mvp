# src/engineering_intelligence/claim_conflict_service.py
"""
EPI-14 技术冲突检测

三类冲突：
1. claim_status_conflict：同一 construct 下同类 claim 一个 supported 一个 contradicted
2. result_direction_conflict：同一 construct 下同类 result 方向相反（positive vs negative）
3. cross_construct_conflict：同一 strategy 下不同 construct 的结果方向相反

输出：
- 返回冲突列表
- 可选建立 CONTRADICTS 关系
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


def _find_claim_status_conflicts(driver: Driver, construct_id: Optional[str] = None) -> List[Dict]:
    """同一 construct 下，同类 claim 中出现 supported vs contradicted"""
    where_clause = "WHERE ec.construct_id = $cid" if construct_id else ""
    params = {"cid": construct_id} if construct_id else {}

    with driver.session() as s:
        rows = list(s.run(f"""
            MATCH (tc1:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec:EngineeredPhageConstruct)
            MATCH (tc2:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            {where_clause}
            WHERE tc1.claim_id < tc2.claim_id
              AND tc1.claim_type = tc2.claim_type
              AND tc1.claim_status = 'supported'
              AND tc2.claim_status = 'contradicted'
            RETURN ec.construct_id AS construct_id,
                   ec.public_name AS construct_name,
                   tc1.claim_id AS claim_a_id, tc1.claim_text AS claim_a_text,
                   tc2.claim_id AS claim_b_id, tc2.claim_text AS claim_b_text,
                   tc1.claim_type AS claim_type
        """, **params))
    return [
        {
            "conflict_type": "claim_status_conflict",
            "construct_id": r["construct_id"],
            "construct_name": r["construct_name"],
            "claim_type": r["claim_type"],
            "claim_a_id": r["claim_a_id"], "claim_a_text": r["claim_a_text"][:100],
            "claim_b_id": r["claim_b_id"], "claim_b_text": r["claim_b_text"][:100],
        }
        for r in rows
    ]


def _find_result_direction_conflicts(driver: Driver, construct_id: Optional[str] = None) -> List[Dict]:
    """同一 construct 下，同类 result 方向相反"""
    where_clause = "WHERE ec.construct_id = $cid" if construct_id else ""
    params = {"cid": construct_id} if construct_id else {}

    with driver.session() as s:
        rows = list(s.run(f"""
            MATCH (tr1:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
            MATCH (tr2:TechnicalResult)-[:RESULT_FOR]->(ec)
            {where_clause}
            WHERE tr1.result_id < tr2.result_id
              AND tr1.result_type = tr2.result_type
              AND tr1.outcome_direction = 'positive'
              AND tr2.outcome_direction = 'negative'
            RETURN ec.construct_id AS construct_id,
                   ec.public_name AS construct_name,
                   tr1.result_id AS result_a_id, tr1.metric_name AS metric_a,
                   tr2.result_id AS result_b_id, tr2.metric_name AS metric_b,
                   tr1.result_type AS result_type
        """, **params))
    return [
        {
            "conflict_type": "result_direction_conflict",
            "construct_id": r["construct_id"],
            "construct_name": r["construct_name"],
            "result_type": r["result_type"],
            "result_a_id": r["result_a_id"], "metric_a": r["metric_a"],
            "result_b_id": r["result_b_id"], "metric_b": r["metric_b"],
        }
        for r in rows
    ]


def _find_cross_construct_conflicts(driver: Driver, strategy_id: Optional[str] = None) -> List[Dict]:
    """同一 strategy 下不同 construct 的结果方向相反"""
    where_clause = "WHERE es.strategy_id = $sid" if strategy_id else ""
    params = {"sid": strategy_id} if strategy_id else {}

    with driver.session() as s:
        rows = list(s.run(f"""
            MATCH (ec1:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy)
            MATCH (ec2:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es)
            {where_clause}
            WHERE ec1.construct_id < ec2.construct_id
            MATCH (tr1:TechnicalResult)-[:RESULT_FOR]->(ec1)
            MATCH (tr2:TechnicalResult)-[:RESULT_FOR]->(ec2)
            WHERE tr1.result_type = tr2.result_type
              AND tr1.outcome_direction = 'positive'
              AND tr2.outcome_direction = 'negative'
            RETURN es.strategy_id AS strategy_id,
                   es.strategy_type AS strategy_type,
                   ec1.construct_id AS construct_a_id, ec1.public_name AS construct_a_name,
                   ec2.construct_id AS construct_b_id, ec2.public_name AS construct_b_name,
                   tr1.result_id AS result_a_id, tr2.result_id AS result_b_id,
                   tr1.result_type AS result_type
        """, **params))
    return [
        {
            "conflict_type": "cross_construct_conflict",
            "strategy_id": r["strategy_id"],
            "strategy_type": r["strategy_type"],
            "construct_a_id": r["construct_a_id"], "construct_a_name": r["construct_a_name"],
            "construct_b_id": r["construct_b_id"], "construct_b_name": r["construct_b_name"],
            "result_type": r["result_type"],
            "result_a_id": r["result_a_id"], "result_b_id": r["result_b_id"],
        }
        for r in rows
    ]


def detect_conflicts(
    driver: Driver,
    construct_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    persist: bool = False,
    actor_id: str = "conflict_detector",
) -> Dict:
    """
    主入口：检测所有冲突。

    - 若给 construct_id：只在该构建体内检测
    - 若给 strategy_id：只在该策略内检测跨构建体冲突
    - 都不给：全局检测
    """
    results = {
        "claim_status_conflicts": [],
        "result_direction_conflicts": [],
        "cross_construct_conflicts": [],
        "total_conflicts": 0,
    }

    if construct_id or not strategy_id:
        results["claim_status_conflicts"] = _find_claim_status_conflicts(driver, construct_id)
        results["result_direction_conflicts"] = _find_result_direction_conflicts(driver, construct_id)

    if strategy_id or not construct_id:
        results["cross_construct_conflicts"] = _find_cross_construct_conflicts(driver, strategy_id)

    results["total_conflicts"] = (
        len(results["claim_status_conflicts"])
        + len(results["result_direction_conflicts"])
        + len(results["cross_construct_conflicts"])
    )

    if persist and results["total_conflicts"] > 0:
        created = _persist_conflicts(driver, results, actor_id=actor_id)
        results["created_relations"] = created

    return results


def _persist_conflicts(driver: Driver, results: Dict, actor_id: str) -> List[str]:
    """把冲突写成 CONTRADICTS 关系，幂等"""
    created = []
    with driver.session() as s:
        # claim_status_conflict: (tc_a)-[:CONTRADICTS]->(tc_b)
        for c in results.get("claim_status_conflicts", []):
            existing = s.run("""
                MATCH (a:TechnicalClaim {claim_id: $aid})-[r:CONTRADICTS]->(b:TechnicalClaim {claim_id: $bid})
                RETURN r.conflict_id AS cid LIMIT 1
            """, aid=c["claim_a_id"], bid=c["claim_b_id"]).single()
            if existing:
                continue
            cid = f"CONFLICT:{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (a:TechnicalClaim {claim_id: $aid})
                MATCH (b:TechnicalClaim {claim_id: $bid})
                CREATE (a)-[r:CONTRADICTS {
                    conflict_id: $cid,
                    conflict_type: 'claim_status_conflict',
                    claim_type: $ctype,
                    created_at: datetime()
                }]->(b)
            """, aid=c["claim_a_id"], bid=c["claim_b_id"],
                 cid=cid, ctype=c["claim_type"])
            created.append(cid)

        # result_direction_conflict
        for c in results.get("result_direction_conflicts", []):
            existing = s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})-[r:CONTRADICTS]->(b:TechnicalResult {result_id: $bid})
                RETURN r.conflict_id AS cid LIMIT 1
            """, aid=c["result_a_id"], bid=c["result_b_id"]).single()
            if existing:
                continue
            cid = f"CONFLICT:{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})
                MATCH (b:TechnicalResult {result_id: $bid})
                CREATE (a)-[r:CONTRADICTS {
                    conflict_id: $cid,
                    conflict_type: 'result_direction_conflict',
                    result_type: $rtype,
                    created_at: datetime()
                }]->(b)
            """, aid=c["result_a_id"], bid=c["result_b_id"],
                 cid=cid, rtype=c["result_type"])
            created.append(cid)

        # cross_construct_conflict（挂在 result 之间）
        for c in results.get("cross_construct_conflicts", []):
            existing = s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})-[r:CONTRADICTS]->(b:TechnicalResult {result_id: $bid})
                RETURN r.conflict_id AS cid LIMIT 1
            """, aid=c["result_a_id"], bid=c["result_b_id"]).single()
            if existing:
                continue
            cid = f"CONFLICT:{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})
                MATCH (b:TechnicalResult {result_id: $bid})
                CREATE (a)-[r:CONTRADICTS {
                    conflict_id: $cid,
                    conflict_type: 'cross_construct_conflict',
                    strategy_id: $sid,
                    result_type: $rtype,
                    created_at: datetime()
                }]->(b)
            """, aid=c["result_a_id"], bid=c["result_b_id"],
                 cid=cid, sid=c["strategy_id"], rtype=c["result_type"])
            created.append(cid)

    if created:
        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="TechnicalClaim",
            object_id=results.get("construct_id") or results.get("strategy_id") or "global",
            actor_id=actor_id,
            delta={"conflicts_created": len(created)},
            reason=f"技术冲突检测：{len(created)} 条 CONTRADICTS 关系",
        )
    return created


def list_conflicts_for_construct(driver: Driver, construct_id: str) -> List[Dict]:
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (a)-[r:CONTRADICTS]->(b)
            WHERE (a:TechnicalClaim OR a:TechnicalResult)
              AND (b:TechnicalClaim OR b:TechnicalResult)
              AND (r.conflict_type IN ['claim_status_conflict', 'result_direction_conflict'])
              AND EXISTS {
                  MATCH (a)-[]->(ec:EngineeredPhageConstruct {construct_id: $cid})
              }
            RETURN r.conflict_id AS conflict_id,
                   r.conflict_type AS conflict_type,
                   labels(a)[0] AS a_label, a.claim_id AS a_claim_id, a.result_id AS a_result_id,
                   labels(b)[0] AS b_label, b.claim_id AS b_claim_id, b.result_id AS b_result_id
        """, cid=construct_id))
    return [dict(r) for r in rows]