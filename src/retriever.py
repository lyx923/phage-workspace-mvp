# src/retriever.py
from typing import List, Dict, Optional
from neo4j import Driver
from src.data_loader import get_driver
import uuid


def find_matching_phages(
    driver: Driver,
    species: str,
    resistance: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """
    查询匹配该病原菌的所有噬菌体互作关系（基于 LysisAssay）。
    按证据等级排序：L5 > L4 > L3 > L2 > L1，同级别按 result_value DESC。
    """
    # 关联路径：Phage -[:USED_IN]-> LysisAssay -[:TESTED_AGAINST]-> HostStrain -[:BELONGS_TO]-> Pathogen
    # 为了简化查询，我们在 LysisAssay 上保留了 pathogen_id 属性（已在 data_loader 中设置）
    # 这样可以直接匹配 Pathogen，无需经过 HostStrain。
    query = """
    MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)
    MATCH (p:Pathogen {pathogen_id: a.pathogen_id})
    WHERE p.species = $species
      AND ($resistance IS NULL OR p.resistance_mechanism CONTAINS $resistance)
    RETURN ph.phage_id AS phage_id,
           ph.name AS name,
           ph.family AS family,
           ph.receptor_target AS receptor_target,
           a.assay_id AS assay_id,
           a.result AS infection_result,
           a.result_value AS infection_probability,
           a.evidence_level AS evidence_level,
           a.evidence_ref AS evidence_ref,
           a.qc_status AS qc_status
    ORDER BY 
        CASE a.evidence_level
            WHEN 'L5' THEN 1
            WHEN 'L4' THEN 2
            WHEN 'L3' THEN 3
            WHEN 'L2' THEN 4
            WHEN 'L1' THEN 5
            ELSE 6
        END,
        a.result_value DESC
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
    """查询相同病原菌 + 相同/相似感染类型的历史病例（不变，因为 ClinicalCase 结构未改）"""
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


# ==================== 跨病例复用分析（需适配新模型） ====================
def analyze_cross_case_reuse(driver: Driver, case_a_id: str, case_b_id: str) -> Dict:
    """分析病例 B 是否复用了病例 A 的噬菌体经验，适配 LysisAssay"""
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

    phages_used_in_a = [p for p in case_a.get('phages_used', []) if p]
    phages_used_in_b = [p for p in case_b.get('phages_used', []) if p]

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

    # 查找病例 B 的匹配噬菌体（基于 LysisAssay）
    matching_phages = find_matching_phages(
        driver,
        case_b['species'],
        resistance=None,
        limit=50
    )

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
                if evidence_level in ['L3', 'L4', 'L5']:
                    evidence_upgrade = True

    # 判断复用类型
    if any(p in phages_used_in_b for p in phages_used_in_a):
        direct_reuse = True
        reuse_type = "direct_reuse"
        explanation = f"病例 B 直接使用了病例 A 使用过的噬菌体 {', '.join([p for p in phages_used_in_a if p in phages_used_in_b])}。"
        is_reuse_valid = True
    elif evidence_upgrade:
        reuse_type = "evidence_upgrade"
        explanation = f"病例 A (CASE-{case_a_id}) 的治疗经验已编码为 L3/L4/L5 证据，被病例 B 的检索结果引用。"
        is_reuse_valid = True
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


# ==================== 知识复用持久化（新增） ====================
def analyze_and_persist_reuse(
    driver: Driver,
    case_a_id: str,
    case_b_id: str,
    target_package_id: str = "EP-DEMO-001"
) -> Dict:
    """
    一站式函数：分析跨病例复用并持久化为 KnowledgeReuseEvent。
    返回包含分析结果和持久化状态的字典。
    """
    # 1. 分析复用
    result = analyze_cross_case_reuse(driver, case_a_id, case_b_id)
    
    # 如果分析出错（如病例不存在）
    if "error" in result:
        return {
            "analysis": result,
            "persistence": {
                "success": False,
                "message": result["error"],
                "reuse_id": None
            }
        }
    
    # 2. 检查复用是否有效
    if not result.get('is_reuse_valid') or result.get('reuse_type') == 'no_reuse':
        return {
            "analysis": result,
            "persistence": {
                "success": False,
                "message": "复用无效，不创建 KnowledgeReuseEvent",
                "reuse_id": None
            }
        }
    
    phage_names = result['case_a'].get('phages_used', [])
    if not phage_names:
        return {
            "analysis": result,
            "persistence": {
                "success": False,
                "message": "病例 A 无噬菌体记录，无法创建复用事件",
                "reuse_id": None
            }
        }
    
    # 3. 持久化
    with driver.session() as session:
        reuse_id = f"REUSE-{uuid.uuid4().hex[:8].upper()}"
        session.run("""
            CREATE (kre:KnowledgeReuseEvent {
                reuse_event_id: $reuse_id,
                source_object_type: 'ClinicalCase',
                source_object_id: $source_id,
                target_package_id: $target_package_id,
                reuse_type: $reuse_type,
                expert_assessment: 'confirmed',
                retrieval_reason: $reason,
                created_at: datetime()
            })
            WITH kre
            UNWIND $phage_names AS pname
            MATCH (ph:Phage {name: pname})-[:USED_IN]->(a:LysisAssay)
            CREATE (kre)-[:REUSES]->(a)
        """,
        reuse_id=reuse_id,
        source_id=case_a_id,
        target_package_id=target_package_id,
        reuse_type=result['reuse_type'],
        reason=result['explanation'],
        phage_names=phage_names)
        
        return {
            "analysis": result,
            "persistence": {
                "success": True,
                "message": f"✅ KnowledgeReuseEvent 已持久化到 Neo4j (ID: {reuse_id})",
                "reuse_id": reuse_id
            }
        }