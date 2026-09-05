# src/engineering_intelligence/strategy_classifier.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from shared.audit_service import write_audit_event

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
    """
    生成工程策略 ID。
    
    Returns:
        str: 格式为 ENG:STRAT:XXXXXXXX 的策略唯一标识符
    """
    return f"ENG:STRAT:{uuid.uuid4().hex[:8].upper()}"


def create_engineering_strategy(
    driver: Driver,
    strategy_type: str,
    description: Optional[str] = None,
    evidence_maturity: str = "conceptual",
    actor_id: str = "system"
) -> str:
    """
    创建工程策略（PRD 9.2）。
    
    策略类型受 STRATEGY_TYPES 受控词表约束。
    若同类型策略已存在，则直接返回已有 ID（幂等）。
    
    Args:
        driver: Neo4j 数据库驱动
        strategy_type: 策略类型（受控词表）
        description: 策略描述
        evidence_maturity: 证据成熟度（conceptual / in_vitro / in_vivo / clinical）
        actor_id: 操作者标识（默认 system）
    
    Returns:
        str: 策略 ID（ENG:STRAT:XXXXXXXX）
    
    Raises:
        ValueError: 当策略类型不在受控词表中时抛出
    """
    if strategy_type not in STRATEGY_TYPES:
        raise ValueError(f"未知的策略类型: {strategy_type}，可选: {STRATEGY_TYPES}")
    
    strategy_id = generate_strategy_id()
    
    with driver.session() as session:
        # 查重：检查是否已存在同类型的策略（幂等）
        existing = session.run("""
            MATCH (es:EngineeringStrategy {strategy_type: $strategy_type})
            RETURN es.strategy_id AS id
        """, strategy_type=strategy_type).single()
        
        if existing:
            print(f"ℹ️ 策略类型 '{strategy_type}' 已存在，ID: {existing['id']}")
            return existing['id']
        
        # 创建策略节点
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
        
        # 审计日志（使用新版 write_audit_event）
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="EngineeringStrategy",
            object_id=strategy_id,
            actor_id=actor_id,
            delta={"strategy_type": strategy_type},
            reason=f"创建工程策略: {strategy_type}",
        )
        
        return strategy_id


def get_all_strategies(driver: Driver) -> List[Dict]:
    """
    获取所有工程策略。
    
    Args:
        driver: Neo4j 数据库驱动
    
    Returns:
        List[Dict]: 策略列表，按策略类型排序
    """
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
    """
    根据策略类型获取单个策略。
    
    Args:
        driver: Neo4j 数据库驱动
        strategy_type: 策略类型
    
    Returns:
        Optional[Dict]: 策略节点字典，若不存在则返回 None
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (es:EngineeringStrategy {strategy_type: $strategy_type})
            RETURN es
        """, strategy_type=strategy_type).single()
        if result:
            return dict(result['es'])
        return None