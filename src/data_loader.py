from typing import List, Dict, Optional
from neo4j import Driver, Transaction

# ---------- 数据验证 ----------
REQUIRED_CASE_FIELDS = [
    "case_id", "pathogen_id", "species", "resistance_mechanism",
    "infection_type", "infection_site", "specimen_type"
]
ALLOWED_INFECTION_RESULTS = ["Lytic", "No infection", "Partial"]

def validate_case_row(row: Dict) -> List[str]:
    """返回缺失必填字段列表，空列表表示验证通过"""
    missing = [f for f in REQUIRED_CASE_FIELDS if not row.get(f)]
    return missing

# ---------- 导入函数 ----------
def load_cases_from_csv(csv_path: str) -> List[Dict]:
    """读取病例 CSV，返回字典列表（含验证）"""
    import pandas as pd
    df = pd.read_csv(csv_path)
    # 填充 NaN 为空字符串
    df = df.fillna("")
    records = df.to_dict(orient="records")
    
    # 验证每行（可选：打印警告）
    for row in records:
        missing = validate_case_row(row)
        if missing:
            print(f"⚠️ {row.get('case_id', 'unknown')} 缺失字段: {missing}")
    return records

def insert_pathogen(driver: Driver, pathogen_data: Dict) -> str:
    """插入 Pathogen 节点，已存在则更新，返回 pathogen_id"""
    query = """
    MERGE (p:Pathogen {pathogen_id: $pathogen_id})
    SET p.species = $species,
        p.resistance_mechanism = $resistance_mechanism,
        p.resistance_genes = $resistance_genes,
        p.ST_type = $ST_type,
        p.verification_status = $verification_status
    RETURN p.pathogen_id
    """
    with driver.session() as session:
        result = session.run(query, **pathogen_data)
        return result.single()[0]

def insert_clinical_case(driver: Driver, case_data: Dict) -> str:
    """插入 ClinicalCase 节点，建立 INVOLVES_PATHOGEN 关系，返回 case_id"""
    query = """
    MERGE (c:ClinicalCase {case_id: $case_id})
    SET c.infection_type = $infection_type,
        c.infection_site = $infection_site,
        c.specimen_type = $specimen_type,
        c.patient_age_group = $patient_age_group,
        c.comorbidities = $comorbidities,
        c.prior_antibiotics = $prior_antibiotics,
        c.phage_treatment = $phage_treatment,
        c.clinical_outcome = $clinical_outcome,
        c.microbiological_outcome = $microbiological_outcome,
        c.curated_by = $curated_by,
        c.curation_date = $curation_date
    WITH c
    MATCH (p:Pathogen {pathogen_id: $pathogen_id})
    MERGE (c)-[:INVOLVES_PATHOGEN]->(p)
    RETURN c.case_id
    """
    with driver.session() as session:
        result = session.run(query, **case_data)
        return result.single()[0]

def batch_insert_phage_interactions(driver: Driver, csv_path: str) -> int:
    """
    批量插入 Phage + PhageHostInteraction + TARGETS 关系。
    返回插入的 PhageHostInteraction 数量。
    """
    import pandas as pd
    df = pd.read_csv(csv_path).fillna("")
    records = df.to_dict(orient="records")
    
    query_phage = """
    MERGE (ph:Phage {phage_id: $phage_id})
    SET ph.name = $name,
        ph.family = $family,
        ph.receptor_target = $receptor_target,
        ph.lifecycle = $lifecycle,
        ph.safety_flags = $safety_flags,
        ph.genome_accession = $genome_accession
    """
    
    query_interaction = """
    MATCH (ph:Phage {phage_id: $phage_id})
    MATCH (p:Pathogen {pathogen_id: $pathogen_id})
    MERGE (phi:PhageHostInteraction {interaction_id: $interaction_id})
    SET phi.infection_result = $infection_result,
        phi.infection_probability = $infection_probability,
        phi.evidence_level = $evidence_level,
        phi.evidence_ref = $evidence_ref,
        phi.notes = $notes
    MERGE (ph)-[:HAS_INTERACTION]->(phi)
    MERGE (phi)-[:TARGETS]->(p)
    RETURN COUNT(phi)
    """
    
    with driver.session() as session:
        # 先插入所有 Phage 节点
        for row in records:
            session.run(query_phage, **row)
        # 再插入所有 Interaction + 关系
        count = 0
        for row in records:
            result = session.run(query_interaction, **row)
            count += result.single()[0]
    return count