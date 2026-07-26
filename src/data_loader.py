# src/data_loader.py
import pandas as pd
from config import config, get_driver
import os
import argparse

# 必填字段（来自 PRD 6.2 和 9.1）
REQUIRED_CASE_FIELDS = [
    "case_id", "pathogen_id", "species", "resistance_mechanism", 
    "infection_type", "infection_site", "specimen_type", "verification_status"
]

def validate_case_row(row):
    """验证必填字段是否缺失"""
    missing = []
    for field in REQUIRED_CASE_FIELDS:
        if pd.isna(row.get(field)) or str(row.get(field)).strip() == "":
            missing.append(field)
    return missing

def insert_pathogen(tx, data):
    """插入或合并 Pathogen 节点"""
    query = """
    MERGE (p:Pathogen {pathogen_id: $pathogen_id})
    SET p.species = $species,
        p.resistance_mechanism = $resistance_mechanism,
        p.resistance_genes = $resistance_genes,
        p.verification_status = $verification_status
    RETURN p.pathogen_id
    """
    result = tx.run(query, **data)
    return result.single()[0]

def insert_clinical_case(tx, data):
    """插入 ClinicalCase 节点，并与 Pathogen 建立关系，同时建立 TREATED_WITH 关系"""
    # 1. 插入 Pathogen
    insert_pathogen(tx, {
        "pathogen_id": data["pathogen_id"],
        "species": data["species"],
        "resistance_mechanism": data["resistance_mechanism"],
        "resistance_genes": data.get("resistance_genes", "").split(",") if isinstance(data.get("resistance_genes"), str) else [],
        "verification_status": data["verification_status"]
    })
    
    # 2. 创建 ClinicalCase 节点并关联 Pathogen，返回 case_id
    query1 = """
    MERGE (c:ClinicalCase {case_id: $case_id})
    SET c.infection_type = $infection_type,
        c.infection_site = $infection_site,
        c.specimen_type = $specimen_type,
        c.clinical_outcome = $clinical_outcome,
        c.phage_treatment = $phage_treatment,
        c.microbiological_outcome = $microbiological_outcome,
        c.curated_by = $curated_by,
        c.curation_date = $curation_date,
        c.patient_age_group = $patient_age_group,
        c.comorbidities = $comorbidities,
        c.prior_antibiotics = $prior_antibiotics
    WITH c, $pathogen_id AS pathogen_id
    MATCH (p:Pathogen {pathogen_id: pathogen_id})
    MERGE (c)-[:INVOLVES_PATHOGEN]->(p)
    RETURN c.case_id
    """
    result = tx.run(query1, **data)
    record = result.single()
    if record is None:
        raise Exception(f"Failed to create ClinicalCase {data.get('case_id')}")
    case_id = record[0]
    
    # 3. 如果 phage_treatment 不为空，建立 TREATED_WITH 关系（仅当对应的 Phage 节点存在时）
    treatment_str = data.get('phage_treatment')
    if treatment_str and pd.notna(treatment_str) and str(treatment_str).strip() != '':
        phage_names = [x.strip() for x in str(treatment_str).split(',') if x.strip()]
        if phage_names:
            query2 = """
            MATCH (c:ClinicalCase {case_id: $case_id})
            UNWIND $phage_names AS phage_name
            OPTIONAL MATCH (ph:Phage {name: phage_name})
            WITH c, ph
            WHERE ph IS NOT NULL
            MERGE (c)-[:TREATED_WITH]->(ph)
            RETURN count(*) AS cnt
            """
            tx.run(query2, case_id=case_id, phage_names=phage_names)
    
    return case_id

def load_cases_from_csv(csv_path):
    """主入口：读取 CSV 并导入数据库"""
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return
    
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条病例记录")
    
    with get_driver() as driver:
        success_count = 0
        with driver.session() as session:
            for index, row in df.iterrows():
                missing = validate_case_row(row)
                if missing:
                    print(f"⚠️ 第 {index+2} 行 (Case: {row.get('case_id', '未知')}) 缺失必填字段: {missing}，已跳过")
                    continue
                
                row_dict = row.to_dict()
                row_dict["resistance_genes"] = str(row_dict.get("resistance_genes", ""))
                
                # 处理可选字段的 NaN
                optional_fields = [
                    'phage_treatment', 'microbiological_outcome', 'curated_by', 'curation_date',
                    'patient_age_group', 'comorbidities', 'prior_antibiotics'
                ]
                for field in optional_fields:
                    if pd.isna(row_dict.get(field)):
                        row_dict[field] = None
                
                # 将逗号分隔的字符串转换为列表
                if row_dict.get('comorbidities') and isinstance(row_dict['comorbidities'], str):
                    row_dict['comorbidities'] = [x.strip() for x in row_dict['comorbidities'].split(',') if x.strip()]
                if row_dict.get('prior_antibiotics') and isinstance(row_dict['prior_antibiotics'], str):
                    row_dict['prior_antibiotics'] = [x.strip() for x in row_dict['prior_antibiotics'].split(',') if x.strip()]
                
                try:
                    case_id = session.execute_write(insert_clinical_case, row_dict)
                    success_count += 1
                except Exception as e:
                    print(f"❌ 导入失败 (Case: {row_dict.get('case_id')}): {e}")
    
    print(f"\n🎯 导入完成！成功 {success_count} 例，失败 {len(df) - success_count} 例。")
    return success_count


# ========== 噬菌体互作数据导入（FR-2）==========
def load_phages_from_csv(csv_path):
    """从 CSV 导入 Phage 和 PhageHostInteraction 节点，并建立完整关系链"""
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条噬菌体互作记录")

    with get_driver() as driver:
        success_count = 0
        with driver.session() as session:
            for index, row in df.iterrows():
                try:
                    interaction_id = f"{row['phage_id']}_{row['pathogen_id']}"

                    # 1. 创建或合并 Phage 节点
                    session.run("""
                    MERGE (p:Phage {phage_id: $phage_id})
                    SET p.name = $phage_name,
                        p.family = $family,
                        p.receptor_target = $receptor_target
                    """,
                    phage_id=row['phage_id'],
                    phage_name=row['phage_name'],
                    family=row.get('family') if pd.notna(row.get('family')) else None,
                    receptor_target=row.get('receptor_target') if pd.notna(row.get('receptor_target')) else None)

                    # 2. 【关键修复】确保 Pathogen 节点存在（只设置 pathogen_id，后续会被 insert_pathogen 补齐）
                    session.run("MERGE (p:Pathogen {pathogen_id: $pathogen_id})", pathogen_id=row['pathogen_id'])

                    # 3. 解析 evidence_ref
                    evidence_ref_str = row.get('evidence_ref', '')
                    if pd.isna(evidence_ref_str) or str(evidence_ref_str).strip() == '':
                        evidence_ref_list = []
                    else:
                        evidence_ref_list = [x.strip() for x in str(evidence_ref_str).split(',') if x.strip()]

                    # 4. 创建 PhageHostInteraction 节点并建立关系
                    result = session.run("""
                    MERGE (i:PhageHostInteraction {interaction_id: $interaction_id})
                    SET i.phage_id = $phage_id,
                        i.pathogen_id = $pathogen_id,
                        i.infection_result = $infection_result,
                        i.infection_probability = $infection_probability,
                        i.evidence_level = $evidence_level,
                        i.evidence_ref = $evidence_ref,
                        i.notes = $notes
                    WITH i
                    MATCH (ph:Phage {phage_id: $phage_id})
                    MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                    MERGE (ph)-[:HAS_INTERACTION]->(i)
                    MERGE (i)-[:TARGETS]->(p)
                    RETURN count(*) AS created
                    """,
                    interaction_id=interaction_id,
                    phage_id=row['phage_id'],
                    pathogen_id=row['pathogen_id'],
                    infection_result=row.get('infection_result') if pd.notna(row.get('infection_result')) else None,
                    infection_probability=float(row['infection_probability']) if pd.notna(row.get('infection_probability')) else None,
                    evidence_level=row['evidence_level'] if pd.notna(row.get('evidence_level')) else None,
                    evidence_ref=evidence_ref_list,
                    notes=row.get('notes') if pd.notna(row.get('notes')) else None)

                    created = result.single()['created']
                    success_count += 1
                except Exception as e:
                    print(f"   ❌ 导入失败 (第 {index+2} 行): {e}")

        print(f"\n🎯 噬菌体互作导入完成！成功 {success_count} 条记录。")

# ========== 从裂解谱 CSV 导入 ==========
# ========== 从裂解谱 CSV 导入（直接插入，不通过临时文件）==========
def load_phages_from_lysis_csv(csv_path: str, pathogen_id: str = "PATH-003") -> dict:
    """
    从裂解谱 CSV 文件读取数据，直接插入 Neo4j（不依赖临时文件和 load_phages_from_csv）。
    每条互作记录生成唯一的 interaction_id（包含宿主菌株），确保全部插入。
    """
    if not os.path.exists(csv_path):
        alt_path = os.path.join("data", os.path.basename(csv_path))
        if os.path.exists(alt_path):
            csv_path = alt_path
        else:
            print(f"❌ 文件不存在: {csv_path}")
            return {"error": "文件不存在"}

    df = pd.read_csv(csv_path, encoding="utf-8")
    print(f"📂 读取到 {len(df)} 个噬菌体，{len(df.columns)-2} 个宿主菌株")

    phage_col = df.columns[0]
    host_cols = df.columns[1:-1]

    from config import get_driver

    # 确保 Pathogen 节点存在
    with get_driver() as driver:
        with driver.session() as session:
            session.run("""
                MERGE (p:Pathogen {pathogen_id: $pathogen_id})
                SET p.species = 'Klebsiella pneumoniae',
                    p.resistance_mechanism = 'Unknown',
                    p.verification_status = 'MICROBIOLOGY_LAB_VERIFIED'
            """, pathogen_id=pathogen_id)
            print(f"✅ Pathogen {pathogen_id} 已就绪")

    success_count = 0
    total_positive = 0
    phages_set = set()

    with get_driver() as driver:
        with driver.session() as session:
            for idx, row in df.iterrows():
                phage_name = row[phage_col]
                phage_id = f"PHAGE-{phage_name}"
                phages_set.add(phage_id)

                # 确保 Phage 节点存在
                session.run("""
                    MERGE (ph:Phage {phage_id: $phage_id})
                    SET ph.name = $phage_name
                """, phage_id=phage_id, phage_name=phage_name)

                for host in host_cols:
                    if row[host] == 1:
                        total_positive += 1
                        host_strain = host.strip()
                        interaction_id = f"{phage_id}_{pathogen_id}_{host_strain.replace('-', '_')}"

                        try:
                            session.run("""
                                MERGE (phi:PhageHostInteraction {interaction_id: $interaction_id})
                                SET phi.phage_id = $phage_id,
                                    phi.pathogen_id = $pathogen_id,
                                    phi.infection_result = 'Lytic',
                                    phi.infection_probability = 1.0,
                                    phi.evidence_level = 'L2',
                                    phi.evidence_ref = '合作方裂解谱数据',
                                    phi.notes = $notes
                                WITH phi
                                MATCH (ph:Phage {phage_id: $phage_id})
                                MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                                MERGE (ph)-[:HAS_INTERACTION]->(phi)
                                MERGE (phi)-[:TARGETS]->(p)
                            """,
                            interaction_id=interaction_id,
                            phage_id=phage_id,
                            pathogen_id=pathogen_id,
                            notes=f"宿主菌株: {host_strain}"
                            )
                            success_count += 1
                            if success_count % 100 == 0:
                                print(f"   已处理 {success_count} 条互作...")
                        except Exception as e:
                            print(f"   ❌ 导入失败 (phage: {phage_name}, host: {host_strain}): {e}")

    print(f"\n🎯 导入完成：")
    print(f"   - 噬菌体数: {len(phages_set)} 个")
    print(f"   - 阳性互作记录: {total_positive} 条")
    print(f"   - 成功插入: {success_count} 条")

    with get_driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (phi:PhageHostInteraction) RETURN count(phi) AS total")
            total = result.single()["total"]

    return {
        "total_phages": len(phages_set),
        "positive_interactions": total_positive,
        "total_in_db": total
    }


def load_phages_from_lysis_csv_simple(csv_path: str = "../data/肺克数据脱敏.csv") -> dict:
    """简化版本，使用默认参数"""
    return load_phages_from_lysis_csv(csv_path, pathogen_id="PATH-003")

# ========== 清空数据库函数 ==========
def clear_database():
    """清空 Neo4j 中所有节点和关系"""
    print("⚠️  正在清空数据库...")
    with get_driver() as driver:
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
    print("✅ 数据库已清空")


# ========== 主入口 ==========
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入病例和噬菌体数据")
    parser.add_argument("--clear", action="store_true", help="清空数据库再导入")
    args = parser.parse_args()

    if args.clear:
        clear_database()
    
    print("\n===== 开始导入噬菌体互作 =====")
    load_phages_from_csv(config.PHAGE_CSV)

    print("===== 开始导入临床病例 =====")
    load_cases_from_csv(config.CASES_CSV)
    
    print("\n🎉 所有数据导入完成！")