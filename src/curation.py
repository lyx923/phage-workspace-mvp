from typing import Dict, List, Optional
from neo4j import Driver

def curate_case_outcome(
    driver: Driver,
    case_id: str,
    treatment: Dict,   # {phage_ids: List[str], route: str, cocktail_name: str}
    outcome: Dict      # {clinical_outcome: str, microbiological_outcome: str}
) -> str:
    """
    更新 ClinicalCase 的治疗和结局字段。
    如果该病例使用的噬菌体有对应的 PhageHostInteraction，
    将其 evidence_level 从 L1/L2 升级为 L3。
    返回更新摘要。
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
    
    # 2. 升级证据等级 L1/L2 → L3
    if treatment.get('phage_ids'):
        upgrade_query = """
        MATCH (c:ClinicalCase {case_id: $case_id})
        MATCH (c)-[:TREATED_WITH]->(ph:Phage)
        MATCH (ph)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)
        WHERE phi.evidence_level IN ['L1', 'L2']
        SET phi.evidence_level = 'L3',
            phi.evidence_ref = CASE 
                WHEN phi.evidence_ref IS NULL THEN [$case_id]
                ELSE phi.evidence_ref + $case_id
            END
        RETURN COUNT(phi) AS upgraded_count
        """
        with driver.session() as session:
            result = session.run(upgrade_query, case_id=case_id)
            count = result.single()['upgraded_count']
            summary.append(f"✅ 升级了 {count} 条 PhageHostInteraction 至 L3")
    
    return "\n".join(summary)