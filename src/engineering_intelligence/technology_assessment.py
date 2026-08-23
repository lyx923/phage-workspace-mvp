# src/engineering_intelligence/technology_assessment.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.foundation.audit_service import log_action

# 受控值
EVIDENCE_MATURITY_LEVELS = ["conceptual", "in_vitro", "in_vivo", "clinical"]
RELEVANCE_LEVELS = ["high", "medium", "low", "unknown"]
RISK_LEVELS = ["high", "medium", "low", "unknown"]

def generate_assessment_id() -> str:
    return f"ENG:ASSESS:{uuid.uuid4().hex[:8].upper()}"

def create_technology_assessment(
    driver: Driver,
    subject_type: str,  # "construct" or "strategy"
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
    基于已审核证据进行结构化评估
    """
    # 校验输入值
    if evidence_maturity not in EVIDENCE_MATURITY_LEVELS:
        raise ValueError(f"证据成熟度必须是以下之一: {EVIDENCE_MATURITY_LEVELS}")
    if technical_relevance not in RELEVANCE_LEVELS:
        raise ValueError(f"技术相关性必须是以下之一: {RELEVANCE_LEVELS}")
    
    assessment_id = generate_assessment_id()
    
    with driver.session() as session:
        # 检查主题是否存在
        if subject_type == "construct":
            check = session.run(
                "MATCH (ec:EngineeredPhageConstruct {construct_id: $sid}) RETURN ec",
                sid=subject_id
            ).single()
        elif subject_type == "strategy":
            check = session.run(
                "MATCH (es:EngineeringStrategy {strategy_id: $sid}) RETURN es",
                sid=subject_id
            ).single()
        else:
            raise ValueError("subject_type 必须是 'construct' 或 'strategy'")
        
        if not check:
            raise ValueError(f"{subject_type} {subject_id} 不存在")
        
        # 创建评估节点
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
        
        # 建立 ASSESSES 关系
        if subject_type == "construct":
            session.run("""
                MATCH (ta:TechnologyAssessment {technology_assessment_id: $assessment_id})
                MATCH (ec:EngineeredPhageConstruct {construct_id: $subject_id})
                CREATE (ta)-[:ASSESSES]->(ec)
            """, assessment_id=assessment_id, subject_id=subject_id)
        elif subject_type == "strategy":
            session.run("""
                MATCH (ta:TechnologyAssessment {technology_assessment_id: $assessment_id})
                MATCH (es:EngineeringStrategy {strategy_id: $subject_id})
                CREATE (ta)-[:ASSESSES]->(es)
            """, assessment_id=assessment_id, subject_id=subject_id)
        
        log_action(driver, domain="ci", action_type="CREATE_TECH_ASSESSMENT",
                   object_type="TechnologyAssessment", object_id=assessment_id,
                   actor_id=actor_id)
        
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
    获取某个策略类型下所有相关的技术评估
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

def suggest_assessment_from_evidence(
    driver: Driver,
    construct_id: str
) -> Dict:
    """
    根据现有主张和结果，自动建议评估值
    """
    with driver.session() as session:
        # 获取构建体的主张和结果
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
        
        # 根据证据自动推断成熟度
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
        
        # 根据结果方向推断技术相关性
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