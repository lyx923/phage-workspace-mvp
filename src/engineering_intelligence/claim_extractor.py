# src/engineering_intelligence/claim_extractor.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.foundation.audit_service import write_audit_event


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
    claimant_type: str = "publication",  # publication, patent, company, investigator
    evidence_context: Optional[str] = None,  # in_vitro, animal, clinical, computational
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
        # 查重
        existing = session.run("""
            MATCH (tc:TechnicalClaim {claim_text: $claim_text})
            RETURN tc.claim_id AS id
        """, claim_text=claim_text).single()
        if existing:
            print(f"ℹ️ 主张已存在，ID: {existing['id']}")
            return existing['id']

        # 创建主张节点
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

        # 关联构建体
        if construct_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                CREATE (tc)-[:CLAIMS_ABOUT]->(ec)
            """, claim_id=claim_id, construct_id=construct_id)

        # 关联策略
        if strategy_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (es:EngineeringStrategy {strategy_id: $strategy_id})
                CREATE (tc)-[:CLAIMS_ABOUT]->(es)
            """, claim_id=claim_id, strategy_id=strategy_id)

        # 关联来源
        if source_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (s:SourceArtifact {source_id: $source_id})
                CREATE (tc)-[:SUPPORTED_BY]->(s)
            """, claim_id=claim_id, source_id=source_id)

        # 审计日志（新版）
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

def create_technical_result(
    driver: Driver,
    result_type: str,  # host_range, lysis, biofilm, safety, in_vivo, computational
    study_context: str,  # in_vitro, animal, clinical, computational
    outcome_direction: Optional[str] = None,  # positive, negative, mixed, neutral
    metric_name: Optional[str] = None,
    metric_value: Optional[float] = None,
    metric_unit: Optional[str] = None,
    comparator: Optional[str] = None,
    sample_size: Optional[int] = None,
    limitation_summary: Optional[str] = None,
    reproducibility_status: str = "single_source",
    construct_id: Optional[str] = None,
    source_id: Optional[str] = None,
    actor_id: str = "system"
) -> str:
    """
    PRD 9.5: 创建技术结果（TechnicalResult）
    """
    result_id = generate_result_id()

    with driver.session() as session:
        # 创建结果节点
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

        # 关联构建体
        if construct_id:
            session.run("""
                MATCH (tr:TechnicalResult {result_id: $result_id})
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                CREATE (tr)-[:RESULT_FOR]->(ec)
            """, result_id=result_id, construct_id=construct_id)

        # 关联来源
        if source_id:
            session.run("""
                MATCH (tr:TechnicalResult {result_id: $result_id})
                MATCH (s:SourceArtifact {source_id: $source_id})
                CREATE (tr)-[:REPORTED_IN]->(s)
            """, result_id=result_id, source_id=source_id)

        # 审计日志（新版）
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="TechnicalResult",
            object_id=result_id,
            actor_id=actor_id,
            delta={"result_type": result_type, "study_context": study_context},
            reason=f"创建技术结果: {result_type}"
        )

        return result_id


# ==================== 查询和关联功能 ====================

def get_claims_by_construct(driver: Driver, construct_id: str) -> List[Dict]:
    """获取某个构建体的所有主张"""
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
    """获取某个构建体的所有结果"""
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

        # 分析缺口
        claims = [dict(c) for c in record['claims']]
        results = [dict(r) for r in record['results']]

        gaps = []
        for claim in claims:
            claim_type = claim.get('claim_type')
            # 检查是否有对应类型的结果
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
                # 检查结果是否支持主张（简化：仅检查方向）
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