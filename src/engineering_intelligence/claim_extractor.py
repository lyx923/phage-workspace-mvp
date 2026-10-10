# src/engineering_intelligence/claim_extractor.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_claim_id() -> str:
    return f"ENG:CLAIM:{uuid.uuid4().hex[:8].upper()}"


def generate_result_id() -> str:
    return f"ENG:RESULT:{uuid.uuid4().hex[:8].upper()}"


# ==================== TechnicalClaim ====================

def create_technical_claim(
    driver: Driver,
    claim_type: str,  # efficacy, host_range, safety, manufacturability, mechanism
    claim_text: str,
    exact_quote: Optional[str] = None,
    claimant_type: str = "publication",
    evidence_context: Optional[str] = None,
    construct_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    source_id: Optional[str] = None,
    actor_id: str = "system"
) -> str:
    """
    PRD 9.4: 创建技术主张（TechnicalClaim）
    """
    claim_id = generate_claim_id()

    with driver.session() as session:
        existing = session.run("""
            MATCH (tc:TechnicalClaim {claim_text: $claim_text})
            RETURN tc.claim_id AS id
        """, claim_text=claim_text).single()
        if existing:
            print(f"ℹ️ 主张已存在，ID: {existing['id']}")
            return existing['id']

        session.run("""
            CREATE (tc:TechnicalClaim {
                claim_id: $claim_id,
                claim_type: $claim_type,
                claim_text: $claim_text,
                exact_quote: $exact_quote,
                claimant_type: $claimant_type,
                evidence_context: $evidence_context,
                claim_status: 'asserted',
                confidence: 'medium',
                review_status: 'pending',
                extracted_by: 'human',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, claim_id=claim_id, claim_type=claim_type, claim_text=claim_text,
           exact_quote=exact_quote, claimant_type=claimant_type,
           evidence_context=evidence_context)

        if construct_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MERGE (tc)-[:CLAIMS_ABOUT]->(ec)
            """, claim_id=claim_id, construct_id=construct_id)

        if strategy_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (es:EngineeringStrategy {strategy_id: $strategy_id})
                MERGE (tc)-[:CLAIMS_ABOUT]->(es)
            """, claim_id=claim_id, strategy_id=strategy_id)

        if source_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (s:SourceArtifact {source_id: $source_id})
                MERGE (tc)-[:SUPPORTED_BY]->(s)
            """, claim_id=claim_id, source_id=source_id)

        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="TechnicalClaim",
            object_id=claim_id,
            actor_id=actor_id,
            delta={"claim_type": claim_type, "claimant_type": claimant_type},
            reason=f"创建技术主张: {claim_type}"
        )

        return claim_id


# ==================== TechnicalResult ====================

def _direction_to_relation(outcome_direction: Optional[str]) -> Optional[str]:
    """
    v0.6 P1-8：把 outcome_direction 映射为 SUPPORTED_OR_CHALLENGES 的语义。
    positive → 'SUPPORTED'
    negative → 'CHALLENGES'
    其它（mixed / neutral / None）→ None，不建关系
    """
    if outcome_direction == "positive":
        return "SUPPORTED"
    if outcome_direction == "negative":
        return "CHALLENGES"
    return None


def create_technical_result(
    driver: Driver,
    result_type: str,
    study_context: str,
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
    claim_id: Optional[str] = None,           # v0.6 P1-8：显式关联 claim
    actor_id: str = "system"
) -> str:
    """
    PRD 9.5: 创建技术结果（TechnicalResult）。

    v0.6 P1-8 新增：
      - claim_id 参数：直接建立 (tr)-[:SUPPORTED_OR_CHALLENGES]->(tc)
      - outcome_direction 决定语义：
          positive → relationship_verdict = 'SUPPORTED'
          negative → relationship_verdict = 'CHALLENGES'
          其它     → 不建关系
    """
    result_id = generate_result_id()

    with driver.session() as session:
        session.run("""
            CREATE (tr:TechnicalResult {
                result_id: $result_id,
                result_type: $result_type,
                study_context: $study_context,
                outcome_direction: $outcome_direction,
                metric_name: $metric_name,
                metric_value: $metric_value,
                metric_unit: $metric_unit,
                comparator: $comparator,
                sample_size: $sample_size,
                limitation_summary: $limitation_summary,
                reproducibility_status: $reproducibility_status,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, result_id=result_id, result_type=result_type,
           study_context=study_context, outcome_direction=outcome_direction,
           metric_name=metric_name, metric_value=metric_value,
           metric_unit=metric_unit, comparator=comparator,
           sample_size=sample_size, limitation_summary=limitation_summary,
           reproducibility_status=reproducibility_status)

        if construct_id:
            session.run("""
                MATCH (tr:TechnicalResult {result_id: $result_id})
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MERGE (tr)-[:RESULT_FOR]->(ec)
            """, result_id=result_id, construct_id=construct_id)

        if source_id:
            session.run("""
                MATCH (tr:TechnicalResult {result_id: $result_id})
                MATCH (s:SourceArtifact {source_id: $source_id})
                MERGE (tr)-[:REPORTED_IN]->(s)
            """, result_id=result_id, source_id=source_id)

        # v0.6 P1-8：SUPPORTED_OR_CHALLENGES 关系
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
            driver,
            action_type="CREATE",
            object_type="TechnicalResult",
            object_id=result_id,
            actor_id=actor_id,
            delta={
                "result_type": result_type,
                "study_context": study_context,
                "outcome_direction": outcome_direction,
                "claim_id": claim_id,
                "verdict": verdict,
                "linked_claim": linked_claim,
            },
            reason=f"创建技术结果: {result_type}"
        )

        return result_id


# ==================== v0.6 P1-8：独立挂载与回填 ====================

def link_result_to_claim(
    driver: Driver,
    result_id: str,
    claim_id: str,
    actor_id: str = "system",
) -> bool:
    """
    v0.6 P1-8：建立 (TechnicalResult)-[:SUPPORTED_OR_CHALLENGES]->(TechnicalClaim)。
    关系方向由 result.outcome_direction 决定。
    幂等：已存在的同向关系直接返回 True。
    """
    with driver.session() as s:
        tr = s.run(
            """
            MATCH (tr:TechnicalResult {result_id: $rid})
            RETURN tr.outcome_direction AS od LIMIT 1
            """,
            rid=result_id,
        ).single()
        if not tr:
            raise ValueError(f"TechnicalResult {result_id} 不存在")
        tc = s.run(
            "MATCH (tc:TechnicalClaim {claim_id: $cid}) RETURN tc LIMIT 1",
            cid=claim_id,
        ).single()
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
        driver,
        action_type="LINK_CREATE",
        object_type="TechnicalResult",
        object_id=result_id,
        actor_id=actor_id,
        delta={
            "relation": "SUPPORTED_OR_CHALLENGES",
            "claim_id": claim_id,
            "verdict": verdict,
        },
        reason=f"结果 {result_id} {verdict} 主张 {claim_id}",
    )
    return True


def backfill_result_to_claim(
    driver: Driver,
    actor_id: str = "backfill",
) -> dict:
    """
    v0.6 P1-8 backfill：
    从语义推断 (TechnicalResult)-[:SUPPORTED_OR_CHALLENGES]->(TechnicalClaim)。

    推导规则：
      - result 和 claim 在同一个 construct 上（都通过 CLAIMS_ABOUT / RESULT_FOR 关联）
      - result.result_type == claim.claim_type
      - result.outcome_direction 可判定方向（positive / negative）
      - 关系不存在时才建立

    返回：{"created": N, "details": [...]}
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
            RETURN tr.result_id AS rid,
                   tr.outcome_direction AS od,
                   tc.claim_id AS cid,
                   ec.construct_id AS ecid
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
            details.append({
                "result_id": r["rid"],
                "claim_id": r["cid"],
                "construct_id": r["ecid"],
                "verdict": verdict,
            })

    if created > 0:
        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="TechnicalResult",
            object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_supported_or_challenges": created, "details": details},
            reason=f"回填 SUPPORTED_OR_CHALLENGES 关系：{created} 条",
        )

    return {"created": created, "details": details}


# ==================== 查询 ====================

def get_claims_by_construct(driver: Driver, construct_id: str) -> List[Dict]:
    with driver.session() as session:
        result = session.run("""
            MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tc)-[:SUPPORTED_BY]->(s:SourceArtifact)
            RETURN tc.claim_id AS id,
                   tc.claim_type AS claim_type,
                   tc.claim_text AS claim_text,
                   tc.claimant_type AS claimant_type,
                   tc.evidence_context AS evidence_context,
                   tc.claim_status AS status,
                   s.source_id AS source_id,
                   s.title AS source_title
            ORDER BY tc.created_at DESC
        """, construct_id=construct_id)
        return [dict(record) for record in result]


def get_results_by_construct(driver: Driver, construct_id: str) -> List[Dict]:
    with driver.session() as session:
        result = session.run("""
            MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tr)-[:REPORTED_IN]->(s:SourceArtifact)
            RETURN tr.result_id AS id,
                   tr.result_type AS result_type,
                   tr.study_context AS study_context,
                   tr.outcome_direction AS outcome_direction,
                   tr.metric_name AS metric_name,
                   tr.metric_value AS metric_value,
                   tr.metric_unit AS metric_unit,
                   tr.sample_size AS sample_size,
                   tr.limitation_summary AS limitation_summary,
                   tr.reproducibility_status AS reproducibility_status,
                   s.source_id AS source_id,
                   s.title AS source_title
            ORDER BY tr.created_at DESC
        """, construct_id=construct_id)
        return [dict(record) for record in result]


def get_verdicts_for_claim(driver: Driver, claim_id: str) -> List[Dict]:
    """
    v0.6 P1-8：查询某个 claim 的所有支持/挑战判定。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (tr:TechnicalResult)-[r:SUPPORTED_OR_CHALLENGES]->(tc:TechnicalClaim {claim_id: $cid})
            RETURN tr.result_id AS result_id,
                   tr.result_type AS result_type,
                   tr.outcome_direction AS outcome_direction,
                   r.verdict AS verdict,
                   r.created_at AS created_at
            ORDER BY r.created_at DESC
        """, cid=claim_id)
        return [dict(record) for record in result]


def detect_claim_evidence_gaps(driver: Driver, construct_id: str) -> Dict:
    """
    PRD 13.6: 识别主张与公开证据之间的缺口
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            WITH ec, COLLECT(DISTINCT tc) AS claims, COLLECT(DISTINCT tr) AS results
            RETURN ec.construct_id AS construct_id,
                   ec.public_name AS name,
                   SIZE(claims) AS total_claims,
                   SIZE(results) AS total_results,
                   claims,
                   results
        """, construct_id=construct_id)
        record = result.single()
        if not record:
            return {"error": f"构建体 {construct_id} 不存在"}

        claims = [dict(c) for c in record['claims']]
        results = [dict(r) for r in record['results']]

        gaps = []
        for claim in claims:
            claim_type = claim.get('claim_type')
            matching_results = [r for r in results if r.get('result_type') == claim_type]
            if not matching_results:
                gaps.append({
                    "claim_id": claim['claim_id'],
                    "claimed_capability": claim.get('claim_text', '')[:50],
                    "available_results": [],
                    "missing_validation_stage": claim.get('evidence_context', 'unknown'),
                    "gap_severity": "high"
                })
            else:
                for result in matching_results:
                    if result.get('outcome_direction') not in ['positive', None]:
                        gaps.append({
                            "claim_id": claim['claim_id'],
                            "claimed_capability": claim.get('claim_text', '')[:50],
                            "available_results": [result.get('result_type')],
                            "missing_validation_stage": result.get('study_context', 'unknown'),
                            "gap_severity": "medium"
                        })

        return {
            "construct_id": construct_id,
            "construct_name": record['name'],
            "total_claims": record['total_claims'],
            "total_results": record['total_results'],
            "gaps": gaps,
            "has_gap": len(gaps) > 0
        }