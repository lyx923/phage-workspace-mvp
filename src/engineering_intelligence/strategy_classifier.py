# src/engineering_intelligence/strategy_classifier.py
import uuid
from typing import Optional, List
from neo4j import Driver
from src.foundation.audit_service import log_action

# PRD 9.2 首版分类
STRATEGY_TYPES = [
    "host_range_expansion",
    "tail_fiber_engineering",
    "receptor_binding_engineering",
    "lysis_enhancement",
    "lysogeny_removal",
    "biofilm_disruption",
    "payload_delivery",
    "anti_resistance_payload",
    "anti_virulence_payload",
    "immune_modulation",
    "phage_display",
    "genome_minimization",
    "manufacturability_optimization",
    "stability_optimization",
    "delivery_optimization",
    "other"
]

def generate_strategy_id() -> str:
    return f"ENG:STRAT:{uuid.uuid4().hex[:8].upper()}"

def create_engineering_strategy(
    driver: Driver,
    strategy_type: str,
    description: Optional[str] = None,
    evidence_maturity: str = "conceptual",
    actor_id: str = "system"
) -> str:
    """
    创建工程策略（EngineeringStrategy）
    """
    if strategy_type not in STRATEGY_TYPES:
        raise ValueError(f"未知的策略类型: {strategy_type}，可选: {STRATEGY_TYPES}")
    
    strategy_id = generate_strategy_id()
    
    with driver.session() as session:
        # 查重：检查是否已存在同类型的策略
        existing = session.run("""
            MATCH (es:EngineeringStrategy {strategy_type: $strategy_type})
            RETURN es.strategy_id AS id
        """, strategy_type=strategy_type).single()
        
        if existing:
            print(f"ℹ️ 策略类型 '{strategy_type}' 已存在，ID: {existing['id']}")
            return existing['id']
        
        session.run("""
            CREATE (es:EngineeringStrategy {
                strategy_id: $strategy_id,
                strategy_type: $strategy_type,
                description: $description,
                evidence_maturity: $evidence_maturity,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, strategy_id=strategy_id, strategy_type=strategy_type,
           description=description, evidence_maturity=evidence_maturity)
        
        log_action(driver, domain="ci", action_type="CREATE_STRATEGY",
                   object_type="EngineeringStrategy", object_id=strategy_id,
                   actor_id=actor_id, after_snapshot={"strategy_type": strategy_type})
        
        return strategy_id

def get_all_strategies(driver: Driver) -> List[Dict]:
    """获取所有工程策略"""
    with driver.session() as session:
        result = session.run("""
            MATCH (es:EngineeringStrategy)
            RETURN es.strategy_id AS id,
                   es.strategy_type AS strategy_type,
                   es.description AS description,
                   es.evidence_maturity AS evidence_maturity,
                   es.review_status AS review_status,
                   es.created_at AS created_at
            ORDER BY es.strategy_type
        """)
        return [dict(record) for record in result]

def get_strategy_by_type(driver: Driver, strategy_type: str) -> Optional[Dict]:
    """根据策略类型获取策略"""
    with driver.session() as session:
        result = session.run("""
            MATCH (es:EngineeringStrategy {strategy_type: $strategy_type})
            RETURN es
        """, strategy_type=strategy_type).single()
        if result:
            return dict(result['es'])
        return None