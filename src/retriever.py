# src/retriever.py
from typing import List, Dict, Optional
from neo4j import Driver
from src.data_loader import get_driver


def find_matching_phages(
    driver: Driver,
    species: str,
    resistance: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """
    查询匹配该病原菌的所有噬菌体互作关系。
    按证据等级排序：L5 > L4 > L3 > L2 > L1，同级别按 infection_probability DESC。
    """
    query = """
    MATCH (ph:Phage)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)-[:TARGETS]->(p:Pathogen)
    WHERE p.species = $species
      AND ($resistance IS NULL OR p.resistance_mechanism CONTAINS $resistance)
    RETURN ph.phage_id AS phage_id,
           ph.name AS name,
           ph.family AS family,
           ph.receptor_target AS receptor_target,
           phi.interaction_id AS interaction_id,
           phi.infection_result AS infection_result,
           phi.infection_probability AS infection_probability,
           phi.evidence_level AS evidence_level,
           phi.evidence_ref AS evidence_ref,
           phi.notes AS notes
    ORDER BY 
        CASE phi.evidence_level
            WHEN 'L5' THEN 1
            WHEN 'L4' THEN 2
            WHEN 'L3' THEN 3
            WHEN 'L2' THEN 4
            WHEN 'L1' THEN 5
            ELSE 6
        END,
        phi.infection_probability DESC
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(query, species=species, resistance=resistance, limit=limit)
        return [dict(record) for record in result]


def find_similar_cases(
    driver: Driver,
    species: str,
    infection_type: Optional[str] = None,
    limit: int = 5
) -> List[Dict]:
    """
    查询相同病原菌 + 相同/相似感染类型的历史病例。
    支持双向匹配：'UTI' 能匹配 'Complicated UTI'，反之亦然。
    """
    query = """
    MATCH (c:ClinicalCase)-[:INVOLVES_PATHOGEN]->(p:Pathogen)
    WHERE p.species = $species
      AND (
          $infection_type IS NULL 
          OR c.infection_type CONTAINS $infection_type 
          OR ($infection_type IS NOT NULL AND $infection_type CONTAINS c.infection_type)
      )
    OPTIONAL MATCH (c)-[:TREATED_WITH]->(ph:Phage)
    RETURN c.case_id AS case_id,
           c.infection_type AS infection_type,
           c.infection_site AS infection_site,
           c.specimen_type AS specimen_type,
           c.patient_age_group AS patient_age_group,
           c.comorbidities AS comorbidities,
           c.prior_antibiotics AS prior_antibiotics,
           c.phage_treatment AS phage_treatment,
           c.clinical_outcome AS clinical_outcome,
           c.microbiological_outcome AS microbiological_outcome,
           c.curation_date AS curation_date,
           collect(ph.name) AS phages_used
    ORDER BY c.curation_date DESC
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(query, species=species, infection_type=infection_type, limit=limit)
        return [dict(record) for record in result]


# ==================== 跨病例复用分析 ====================
def analyze_cross_case_reuse(driver: Driver, case_a_id: str, case_b_id: str) -> Dict:
    """
    分析病例 B 是否复用了病例 A 的噬菌体经验。
    增加引用类型标记：direct_reuse / indirect_reference / evidence_upgrade / no_reuse
    """
    with driver.session() as session:
        result_a = session.run("""
            MATCH (c:ClinicalCase {case_id: $case_id})-[:INVOLVES_PATHOGEN]->(p:Pathogen)
            OPTIONAL MATCH (c)-[:TREATED_WITH]->(ph:Phage)
            RETURN c.case_id AS case_id, 
                   p.species AS species, 
                   c.infection_type AS infection_type,
                   c.phage_treatment AS phage_treatment,
                   c.clinical_outcome AS clinical_outcome,
                   collect(ph.name) AS phages_used
        """, case_id=case_a_id)
        case_a = result_a.single()

        result_b = session.run("""
            MATCH (c:ClinicalCase {case_id: $case_id})-[:INVOLVES_PATHOGEN]->(p:Pathogen)
            OPTIONAL MATCH (c)-[:TREATED_WITH]->(ph:Phage)
            RETURN c.case_id AS case_id, 
                   p.species AS species, 
                   c.infection_type AS infection_type,
                   c.phage_treatment AS phage_treatment,
                   c.clinical_outcome AS clinical_outcome,
                   collect(ph.name) AS phages_used
        """, case_id=case_b_id)
        case_b = result_b.single()

    if not case_a or not case_b:
        return {"error": "病例不存在，请检查 case_id"}

    # 解析病例 A 和病例 B 使用的噬菌体
    phages_used_in_a = [p for p in case_a.get('phages_used', []) if p]
    phages_used_in_b = [p for p in case_b.get('phages_used', []) if p]

    # 如果病例 B 没有治疗记录，则无法进行复用分析
    if not phages_used_in_b:
        return {
            "case_a": {
                "id": case_a_id,
                "species": case_a['species'],
                "infection_type": case_a['infection_type'],
                "phages_used": phages_used_in_a,
                "outcome": case_a.get('clinical_outcome')
            },
            "case_b": {
                "id": case_b_id,
                "species": case_b['species'],
                "infection_type": case_b['infection_type'],
                "outcome": case_b.get('clinical_outcome')
            },
            "reuse_type": "no_treatment_data",
            "reused_phages": [],
            "reuse_count": 0,
            "is_reuse_valid": False,
            "explanation": "病例 B 无噬菌体治疗记录，无法判断复用情况"
        }

    # 查找相似病例
    similar_cases_for_b = find_similar_cases(
        driver,
        case_b['species'],
        case_b['infection_type'],
        limit=10
    )
    case_a_in_similar = any(c['case_id'] == case_a_id for c in similar_cases_for_b)

    # 查找病例 B 的匹配噬菌体列表
    matching_phages = find_matching_phages(
        driver,
        case_b['species'],
        resistance=None,
        limit=50
    )

    # 检查病例 A 使用的噬菌体是否出现在病例 B 的匹配列表中
    reused_phages = []
    direct_reuse = False
    evidence_upgrade = False

    for phage_name in phages_used_in_a:
        for mp in matching_phages:
            if mp.get('name') == phage_name:
                evidence_level = mp.get('evidence_level', '')
                reused_phages.append({
                    'name': phage_name,
                    'evidence_level': evidence_level,
                    'probability': mp.get('infection_probability')
                })
                # 检测是否发生了证据等级升级（L4/L5 也视为升级）
                if evidence_level in ['L3', 'L4', 'L5']:
                    evidence_upgrade = True

    # 判断复用类型
    # 1. 直接复用：病例 B 使用了与病例 A 相同的噬菌体
    if any(p in phages_used_in_b for p in phages_used_in_a):
        direct_reuse = True
        reuse_type = "direct_reuse"
        explanation = f"病例 B 直接使用了病例 A 使用过的噬菌体 {', '.join([p for p in phages_used_in_a if p in phages_used_in_b])}。"
        is_reuse_valid = True
    # 2. 证据升级：病例 A 的经验提升了证据等级
    elif evidence_upgrade and case_a_in_similar:
        reuse_type = "evidence_upgrade"
        explanation = f"病例 A (CASE-{case_a_id}) 的治疗经验已编码为 L3/L4/L5 证据，被病例 B 的检索结果引用。"
        is_reuse_valid = True
    # 3. 间接参考：病例 A 出现在相似病例列表中，但未直接使用其噬菌体
    elif case_a_in_similar and not direct_reuse:
        reuse_type = "indirect_reference"
        explanation = f"病例 A (CASE-{case_a_id}) 被列为病例 B 的相似病例，但其噬菌体未被直接使用。"
        is_reuse_valid = True
    # 4. 无复用：无任何关联
    else:
        reuse_type = "no_reuse"
        explanation = f"病例 A (CASE-{case_a_id}) 与病例 B 无显著关联，未发生经验复用。"
        is_reuse_valid = False

    return {
        "case_a": {
            "id": case_a_id,
            "species": case_a['species'],
            "infection_type": case_a['infection_type'],
            "phages_used": phages_used_in_a,
            "outcome": case_a.get('clinical_outcome')
        },
        "case_b": {
            "id": case_b_id,
            "species": case_b['species'],
            "infection_type": case_b['infection_type'],
            "phages_used": phages_used_in_b,
            "outcome": case_b.get('clinical_outcome')
        },
        "reuse_type": reuse_type,
        "reused_phages": reused_phages,
        "reuse_count": len(reused_phages),
        "is_case_a_similar_to_b": case_a_in_similar,
        "is_reuse_valid": is_reuse_valid,
        "explanation": explanation
    }


# ==================== 便捷函数 ====================
def find_matching_phages_simple(species: str, resistance: Optional[str] = None, limit: int = 20) -> List[Dict]:
    with get_driver() as driver:
        return find_matching_phages(driver, species, resistance, limit)


def find_similar_cases_simple(species: str, infection_type: Optional[str] = None, limit: int = 10) -> List[Dict]:
    with get_driver() as driver:
        return find_similar_cases(driver, species, infection_type, limit)


def analyze_cross_case_reuse_simple(case_a_id: str, case_b_id: str) -> Dict:
    with get_driver() as driver:
        return analyze_cross_case_reuse(driver, case_a_id, case_b_id)