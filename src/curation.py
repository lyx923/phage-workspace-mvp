# src/curation.py
from typing import Dict, List, Optional
from neo4j import Driver

# 证据等级升级映射
# L1/L2 → L3（单例临床验证）
# L3 → L4（多中心临床验证）
# L4 → L5（组织学习闭环）
LEVEL_UPGRADE_MAP = {
    'L3': ['L1', 'L2'],
    'L4': ['L3'],
    'L5': ['L4'],
}


def curate_case_outcome(
    driver: Driver,
    case_id: str,
    treatment: Dict,   # {phage_ids: List[str], route: str, cocktail_name: str}
    outcome: Dict,     # {clinical_outcome: str, microbiological_outcome: str}
    target_level: str = 'L3'  # 目标证据等级，默认升级到 L3
) -> str:
    """
    更新 ClinicalCase 的治疗和结局字段。
    如果该病例使用的噬菌体有对应的 PhageHostInteraction，
    将其 evidence_level 从源等级升级为目标等级，并追加病例ID到 evidence_ref（自动去重）。

    Args:
        driver: Neo4j 驱动
        case_id: 病例 ID
        treatment: 治疗方案，包含 phage_ids 和 cocktail_name
        outcome: 临床结局和微生物学结局
        target_level: 目标证据等级 (L3/L4/L5)，默认 L3

    Returns:
        str: 更新摘要
    """
    summary = []
    
    # 1. 更新 ClinicalCase
    update_case_query = """
    MATCH (c:ClinicalCase {case_id: $case_id})
    SET c.phage_treatment = $phage_treatment,
        c.clinical_outcome = $clinical_outcome,
        c.microbiological_outcome = $microbiological_outcome,
        c.curated_by = 'curation.py',
        c.curation_date = date()
    RETURN c.case_id
    """
    with driver.session() as session:
        session.run(update_case_query,
                    case_id=case_id,
                    phage_treatment=treatment.get('cocktail_name', ''),
                    clinical_outcome=outcome.get('clinical_outcome', ''),
                    microbiological_outcome=outcome.get('microbiological_outcome', ''))
        summary.append(f"✅ 病例 {case_id} 已更新结局")
    
    # 2. 升级证据等级
    if treatment.get('phage_ids'):
        # 获取源等级列表
        source_levels = LEVEL_UPGRADE_MAP.get(target_level, ['L1', 'L2'])
        source_levels_str = ', '.join([f"'{l}'" for l in source_levels])
        
        upgrade_query = f"""
        MATCH (c:ClinicalCase {{case_id: $case_id}})
        MATCH (c)-[:TREATED_WITH]->(ph:Phage)
        MATCH (ph)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)
        WHERE phi.evidence_level IN [{source_levels_str}]
        SET phi.evidence_level = $target_level,
            phi.evidence_ref = CASE 
                WHEN phi.evidence_ref IS NULL THEN [$case_id]
                WHEN NOT $case_id IN phi.evidence_ref THEN phi.evidence_ref + $case_id
                ELSE phi.evidence_ref
            END
        RETURN COUNT(phi) AS upgraded_count
        """
        with driver.session() as session:
            result = session.run(upgrade_query, case_id=case_id, target_level=target_level)
            count = result.single()['upgraded_count']
            summary.append(f"✅ 升级了 {count} 条 PhageHostInteraction 从 {', '.join(source_levels)} → {target_level}（并追加病例ID）")
    
    return "\n".join(summary)


def curate_case_by_id(
    driver: Driver,
    case_id: str,
    clinical_outcome: str,
    microbiological_outcome: str,
    target_level: str = 'L3'
) -> str:
    """
    自动根据病例 ID 策展：自动查找该病例使用的噬菌体，升级证据等级。
    适用于批量策展场景。
    
    Args:
        driver: Neo4j 驱动
        case_id: 病例 ID (如 'CASE-002')
        clinical_outcome: 临床结局 (如 'Improved')
        microbiological_outcome: 微生物学结局 (如 'Clearance')
        target_level: 目标证据等级 (L3/L4/L5)，默认 L3
    
    Returns:
        str: 策展摘要
    """
    # 1. 查询该病例使用的噬菌体 ID
    with driver.session() as session:
        result = session.run("""
            MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(ph:Phage)
            RETURN collect(ph.phage_id) AS phage_ids
        """, case_id=case_id)
        record = result.single()
        if not record or not record['phage_ids']:
            return f"⚠️ 病例 {case_id} 没有关联的噬菌体，请先通过 TREATED_WITH 关联。"
        
        phage_ids = record['phage_ids']
    
    # 2. 查询该病例当前的 phage_treatment（用于 cocktail_name）
    with driver.session() as session:
        result = session.run("""
            MATCH (c:ClinicalCase {case_id: $case_id})
            RETURN c.phage_treatment AS treatment
        """, case_id=case_id)
        record = result.single()
        treatment_name = record['treatment'] if record and record['treatment'] else f"{case_id} 治疗方案"
    
    # 3. 调用原有的策展函数（传入 target_level）
    return curate_case_outcome(
        driver,
        case_id=case_id,
        treatment={
            "phage_ids": phage_ids,
            "cocktail_name": treatment_name
        },
        outcome={
            "clinical_outcome": clinical_outcome,
            "microbiological_outcome": microbiological_outcome
        },
        target_level=target_level
    )


# ==================== 便捷函数：批量策展 ====================
def batch_curate_cases(
    driver: Driver,
    cases: List[Dict],
    target_level: str = 'L3'
) -> List[str]:
    """
    批量策展多个病例。
    
    Args:
        driver: Neo4j 驱动
        cases: 病例列表，每个元素包含 case_id, clinical_outcome, microbiological_outcome
        target_level: 目标证据等级，默认 L3
    
    Returns:
        List[str]: 每个病例的策展摘要
    """
    summaries = []
    for case in cases:
        summary = curate_case_by_id(
            driver,
            case_id=case['case_id'],
            clinical_outcome=case['clinical_outcome'],
            microbiological_outcome=case['microbiological_outcome'],
            target_level=target_level
        )
        summaries.append(summary)
    return summaries