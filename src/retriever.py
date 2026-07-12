# src/retriever.py
from typing import List, Dict
from neo4j import Driver

def find_matching_phages(
    driver: Driver,
    species: str,
    resistance: str,
    limit: int = 20
) -> List[Dict]:
    """
    查询匹配该病原菌的所有噬菌体互作关系。
    按 evidence_level DESC, infection_probability DESC 排序。

    Args:
        driver: Neo4j 驱动实例
        species: 病原菌种名，如 "Acinetobacter baumannii"
        resistance: 耐药机制，如 "CR" 或 "MDR"
        limit: 返回结果数量上限

    Returns:
        List[Dict]: 噬菌体互作记录列表，每个字典包含：
            - phage_id, name, family, receptor_target
            - interaction_id, infection_result, infection_probability
            - evidence_level, evidence_ref, notes
    """
    query = """
    MATCH (ph:Phage)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)-[:TARGETS]->(p:Pathogen)
    WHERE p.species = $species
      AND p.resistance_mechanism = $resistance
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
    ORDER BY phi.evidence_level DESC, phi.infection_probability DESC
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(query, species=species, resistance=resistance, limit=limit)
        return [dict(record) for record in result]


def find_similar_cases(
    driver: Driver,
    species: str,
    infection_type: str,
    limit: int = 5
) -> List[Dict]:
    """
    查询相同病原菌 + 相同感染类型的历史病例。

    Args:
        driver: Neo4j 驱动实例
        species: 病原菌种名
        infection_type: 感染类型，如 "VAP", "UTI", "Pneumonia"
        limit: 返回结果数量上限

    Returns:
        List[Dict]: 相似病例列表，每个字典包含：
            - case_id, infection_type, infection_site, specimen_type
            - phage_treatment, clinical_outcome, microbiological_outcome
            - curation_date, phages_used (使用的噬菌体名称列表)
    """
    query = """
    MATCH (c:ClinicalCase)-[:INVOLVES_PATHOGEN]->(p:Pathogen)
    WHERE p.species = $species
      AND c.infection_type = $infection_type
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
    ORDER BY c.case_id DESC
    LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(query, species=species, infection_type=infection_type, limit=limit)
        return [dict(record) for record in result]