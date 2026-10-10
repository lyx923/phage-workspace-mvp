# src/engineering_intelligence/technology_assessment.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event

# 受控值
EVIDENCE_MATURITY_LEVELS = ["conceptual", "in_vitro", "in_vivo", "clinical"]
RELEVANCE_LEVELS = ["high", "medium", "low", "unknown"]
RISK_LEVELS = ["high", "medium", "low", "unknown"]

# v0.6 P1-9：subject_type → (Label, id_prop)
SUBJECT_MAP = {
    "construct": ("EngineeredPhageConstruct", "construct_id"),
    "strategy":  ("EngineeringStrategy",      "strategy_id"),
    "claim":     ("TechnicalClaim",           "claim_id"),   # PRD 9.6
}


def generate_assessment_id() -> str:
    return f"ENG:ASSESS:{uuid.uuid4().hex[:8].upper()}"


def create_technology_assessment(
    driver: Driver,
    subject_type: str,   # "construct" | "strategy" | "claim"
    subject_id: str,
    evidence_maturity: str = "conceptual",
    technical_relevance: str = "medium",
    translational_potential: str = "unknown",
    manufacturability_risk: str = "unknown",
    safety_uncertainty: str = "unknown",
    ip_relevance: str = "unknown",
    internal_capability_gap: str = "unknown",
    assessment_summary: Optional[str] = None,
    actor_id: str = "system"
) -> str:
    """
    PRD 9.6: 创建技术评估（TechnologyAssessment）

    v0.6 P1-9：
      - subject_type 支持 "claim"（PRD 9.6）
      - 建立 (ta)-[:ASSESSES]->(subject)
      - 若 subject_type == "claim"，额外建立 (claim)-[:EVALUATED_BY]->(ta)（PRD 9.4）
    """
    # 校验输入值
    if evidence_maturity not in EVIDENCE_MATURITY_LEVELS:
        raise ValueError(f"证据成熟度必须是以下之一: {EVIDENCE_MATURITY_LEVELS}")
    if technical_relevance not in RELEVANCE_LEVELS:
        raise ValueError(f"技术相关性必须是以下之一: {RELEVANCE_LEVELS}")
    if subject_type not in SUBJECT_MAP:
        raise ValueError(
            f"subject_type 必须是 {list(SUBJECT_MAP.keys())} 之一"
        )

    label, id_prop = SUBJECT_MAP[subject_type]
    assessment_id = generate_assessment_id()

    with driver.session() as session:
        # 1. 检查 subject 是否存在
        check = session.run(
            f"MATCH (n:{label} {{`{id_prop}`: $sid}}) RETURN n LIMIT 1",
            sid=subject_id,
        ).single()
        if not check:
            raise ValueError(f"{subject_type} {subject_id} 不存在")

        # 2. 创建评估节点
        session.run("""
            CREATE (ta:TechnologyAssessment {
                technology_assessment_id: $assessment_id,
                subject_type: $subject_type,
                subject_id: $subject_id,
                evidence_maturity: $evidence_maturity,
                technical_relevance: $technical_relevance,
                translational_potential: $translational_potential,
                manufacturability_risk: $manufacturability_risk,
                safety_uncertainty: $safety_uncertainty,
                ip_relevance: $ip_relevance,
                internal_capability_gap: $internal_capability_gap,
                assessment_summary: $assessment_summary,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, assessment_id=assessment_id, subject_type=subject_type,
           subject_id=subject_id, evidence_maturity=evidence_maturity,
           technical_relevance=technical_relevance,
           translational_potential=translational_potential,
           manufacturability_risk=manufacturability_risk,
           safety_uncertainty=safety_uncertainty,
           ip_relevance=ip_relevance,
           internal_capability_gap=internal_capability_gap,
           assessment_summary=assessment_summary)

        # 3. 建立 ASSESSES 关系
        session.run(f"""
            MATCH (ta:TechnologyAssessment {{technology_assessment_id: $assessment_id}})
            MATCH (n:{label} {{`{id_prop}`: $subject_id}})
            MERGE (ta)-[:ASSESSES]->(n)
        """, assessment_id=assessment_id, subject_id=subject_id)

        # 4. v0.6 P1-9：claim 额外建立反向关系 EVALUATED_BY（PRD 9.4）
        if subject_type == "claim":
            session.run("""
                MATCH (ta:TechnologyAssessment {technology_assessment_id: $assessment_id})
                MATCH (tc:TechnicalClaim {claim_id: $subject_id})
                MERGE (tc)-[:EVALUATED_BY]->(ta)
            """, assessment_id=assessment_id, subject_id=subject_id)

        # 5. 审计日志
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="TechnologyAssessment",
            object_id=assessment_id,
            actor_id=actor_id,
            delta={
                "subject_type": subject_type,
                "subject_id": subject_id,
                "evidence_maturity": evidence_maturity,
                "technical_relevance": technical_relevance,
            },
            reason=f"创建技术评估: {subject_type} {subject_id}"
        )

        return assessment_id


def get_assessment_for_subject(driver: Driver, subject_type: str, subject_id: str) -> Optional[Dict]:
    """获取某个主题的最新技术评估"""
    with driver.session() as session:
        result = session.run("""
            MATCH (ta:TechnologyAssessment {subject_type: $subject_type, subject_id: $subject_id})
            RETURN ta.technology_assessment_id AS id,
                   ta.evidence_maturity AS evidence_maturity,
                   ta.technical_relevance AS technical_relevance,
                   ta.translational_potential AS translational_potential,
                   ta.manufacturability_risk AS manufacturability_risk,
                   ta.safety_uncertainty AS safety_uncertainty,
                   ta.ip_relevance AS ip_relevance,
                   ta.internal_capability_gap AS internal_capability_gap,
                   ta.assessment_summary AS summary,
                   ta.review_status AS review_status,
                   ta.created_at AS created_at
            ORDER BY ta.created_at DESC
            LIMIT 1
        """, subject_type=subject_type, subject_id=subject_id)
        record = result.single()
        return dict(record) if record else None


def get_assessments_by_strategy(driver: Driver, strategy_type: str) -> List[Dict]:
    """
    获取某个策略类型下所有相关的技术评估（construct / strategy）
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (es:EngineeringStrategy {strategy_type: $strategy_type})
            OPTIONAL MATCH (es)<-[:IMPLEMENTS]-(ec:EngineeredPhageConstruct)
            OPTIONAL MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(es)
            OPTIONAL MATCH (ta2:TechnologyAssessment)-[:ASSESSES]->(ec)
            WITH es, ec, ta, ta2
            RETURN es.strategy_id AS strategy_id,
                   es.strategy_type AS strategy_type,
                   ec.construct_id AS construct_id,
                   ec.public_name AS construct_name,
                   ta.technology_assessment_id AS strategy_assessment_id,
                   ta.evidence_maturity AS strategy_maturity,
                   ta.technical_relevance AS strategy_relevance,
                   ta2.technology_assessment_id AS construct_assessment_id,
                   ta2.evidence_maturity AS construct_maturity,
                   ta2.technical_relevance AS construct_relevance
            ORDER BY es.strategy_type
        """, strategy_type=strategy_type)
        return [dict(record) for record in result]


# ============================================================
# v0.6 P1-9：claim 相关查询与回填
# ============================================================

def get_assessments_for_claim(driver: Driver, claim_id: str) -> List[Dict]:
    """
    查询某个 claim 的所有技术评估（通过 EVALUATED_BY 或 ASSESSES 关系）。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (ta:TechnologyAssessment {subject_type: 'claim', subject_id: $cid})
            RETURN ta.technology_assessment_id AS assessment_id,
                   ta.evidence_maturity AS evidence_maturity,
                   ta.technical_relevance AS technical_relevance,
                   ta.translational_potential AS translational_potential,
                   ta.manufacturability_risk AS manufacturability_risk,
                   ta.safety_uncertainty AS safety_uncertainty,
                   ta.ip_relevance AS ip_relevance,
                   ta.internal_capability_gap AS internal_capability_gap,
                   ta.assessment_summary AS summary,
                   ta.review_status AS review_status,
                   ta.created_at AS created_at
            ORDER BY ta.created_at DESC
        """, cid=claim_id)
        return [dict(record) for record in result]


def backfill_claim_evaluated_by(
    driver: Driver,
    actor_id: str = "backfill",
) -> Dict:
    """
    v0.6 P1-9 backfill：
    为所有 (ta:TechnologyAssessment)-[:ASSESSES]->(tc:TechnicalClaim)
    且 ta.subject_type='claim' 的组合，补齐反向关系 (tc)-[:EVALUATED_BY]->(ta)。

    幂等。
    """
    created = 0
    details = []

    with driver.session() as session:
        rows = list(session.run("""
            MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(tc:TechnicalClaim)
            WHERE ta.subject_type = 'claim'
              AND NOT (tc)-[:EVALUATED_BY]->(ta)
            RETURN ta.technology_assessment_id AS taid, tc.claim_id AS cid
        """))

        for r in rows:
            session.run("""
                MATCH (ta:TechnologyAssessment {technology_assessment_id: $taid})
                MATCH (tc:TechnicalClaim {claim_id: $cid})
                MERGE (tc)-[:EVALUATED_BY]->(ta)
            """, taid=r["taid"], cid=r["cid"])
            created += 1
            details.append({"assessment_id": r["taid"], "claim_id": r["cid"]})

    if created > 0:
        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="TechnicalClaim",
            object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_evaluated_by": created, "details": details},
            reason=f"回填 EVALUATED_BY 关系：{created} 条",
        )

    return {"created": created, "details": details}


def suggest_assessment_from_evidence(
    driver: Driver,
    construct_id: str
) -> Dict:
    """
    根据现有主张和结果，自动建议评估值（仅针对 construct）
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            RETURN ec.construct_id AS id,
                   ec.public_name AS name,
                   COLLECT(DISTINCT tc.claim_type) AS claim_types,
                   COLLECT(DISTINCT tr.result_type) AS result_types,
                   COLLECT(DISTINCT tr.study_context) AS study_contexts,
                   COLLECT(DISTINCT tr.outcome_direction) AS outcomes
        """, construct_id=construct_id)
        record = result.single()
        if not record:
            return {"error": f"构建体 {construct_id} 不存在"}

        data = dict(record)

        study_contexts = data.get('study_contexts', [])
        if 'clinical' in study_contexts:
            evidence_maturity = 'clinical'
        elif 'in_vivo' in study_contexts:
            evidence_maturity = 'in_vivo'
        elif 'in_vitro' in study_contexts:
            evidence_maturity = 'in_vitro'
        elif data.get('result_types'):
            evidence_maturity = 'in_vitro'
        elif data.get('claim_types'):
            evidence_maturity = 'conceptual'
        else:
            evidence_maturity = 'conceptual'

        outcomes = data.get('outcomes', [])
        if 'positive' in outcomes:
            technical_relevance = 'high'
        elif 'mixed' in outcomes:
            technical_relevance = 'medium'
        else:
            technical_relevance = 'medium'

        return {
            "construct_id": construct_id,
            "construct_name": data.get('name'),
            "suggested_evidence_maturity": evidence_maturity,
            "suggested_technical_relevance": technical_relevance,
            "has_claims": len(data.get('claim_types', [])) > 0,
            "has_results": len(data.get('result_types', [])) > 0,
            "study_contexts": study_contexts,
            "outcomes": outcomes,
            "note": "此为基于现有证据的自动建议，需专家审核确认"
        }