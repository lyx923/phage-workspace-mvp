# src/scientific/import_service.py
import pandas as pd
from config import config, get_driver
import os
import argparse
import uuid
from typing import List, Dict, Optional

# ================== 必填字段定义 ==================
REQUIRED_CASE_FIELDS = [
    "case_id", "pathogen_id", "species", "resistance_mechanism", 
    "infection_type", "infection_site", "specimen_type", "verification_status"
]

# ================== 辅助函数 ==================
def _get_or_create_host_strain(tx, strain_label: str) -> str:
    """获取或创建 HostStrain 节点，返回 host_strain_id"""
    result = tx.run("""
        MERGE (h:HostStrain {strain_label: $strain_label})
        ON CREATE SET h.host_strain_id = randomUUID()
        RETURN h.host_strain_id AS id
    """, strain_label=strain_label)
    return result.single()["id"]

def _get_or_create_evidence_source(tx, source_ref: str, source_type: str = "unknown") -> str:
    """根据引用标识（如 PMID、CASE-XXX 或固定字符串）获取或创建 EvidenceSource 节点"""
    ev_id = f"EVID-{source_ref.replace(':', '_').replace('/', '_')}"
    result = tx.run("""
        MERGE (e:EvidenceSource {evidence_id: $evidence_id})
        ON CREATE SET e.title = $title,
                      e.evidence_type = $source_type,
                      e.review_status = 'pending',
                      e.created_at = datetime()
        RETURN e.evidence_id AS id
    """, evidence_id=ev_id, title=source_ref, source_type=source_type)
    return result.single()["id"]
def _get_or_create_source_artifact(
    tx, 
    source_ref: str, 
    source_type: str = "unknown", 
    source_domain: str = "scientific",
    title: str = None,
    access_level: str = "internal"
) -> str:
    """
    获取或创建 SourceArtifact 节点（替代 EvidenceSource）
    返回 source_id
    """
    # 生成稳定的 source_id（与之前 EvidenceSource 保持一致，便于迁移）
    source_id = f"SRC-{source_ref.replace(':', '_').replace('/', '_').replace(' ', '_')}"
    if not title:
        title = source_ref
    
    result = tx.run("""
        MERGE (s:SourceArtifact {source_id: $source_id})
        ON CREATE SET 
            s.source_domain = $source_domain,
            s.source_type = $source_type,
            s.title = $title,
            s.access_level = $access_level,
            s.review_status = 'pending',
            s.retrieved_at = datetime(),
            s.created_at = datetime(),
            s.updated_at = datetime(),
            s.schema_version = '1.0.0'
        ON MATCH SET 
            s.updated_at = datetime()
        RETURN s.source_id AS id
    """, 
    source_id=source_id, 
    source_domain=source_domain, 
    source_type=source_type, 
    title=title,
    access_level=access_level)
    
    return result.single()["id"]

def _parse_host_strain_from_notes(notes: str) -> Optional[str]:
    """从 notes 字段中提取宿主菌株编号（若存在）"""
    if not notes:
        return None
    if '宿主菌株:' in notes:
        parts = notes.split('宿主菌株:')
        if len(parts) > 1:
            strain = parts[1].strip()
            if strain:
                return strain
    return None

# ================== 病例导入 ==================
def validate_case_row(row):
    missing = []
    for field in REQUIRED_CASE_FIELDS:
        if pd.isna(row.get(field)) or str(row.get(field)).strip() == "":
            missing.append(field)
    return missing

def insert_pathogen(tx, data):
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
    # 1. 插入 Pathogen
    insert_pathogen(tx, {
        "pathogen_id": data["pathogen_id"],
        "species": data["species"],
        "resistance_mechanism": data["resistance_mechanism"],
        "resistance_genes": data.get("resistance_genes", "").split(",") if isinstance(data.get("resistance_genes"), str) else [],
        "verification_status": data["verification_status"]
    })
    
    # 2. 创建 ClinicalCase
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
    
    # 3. 关联 TREATED_WITH（如果存在噬菌体治疗）—— 已增加去重
    treatment_str = data.get('phage_treatment')
    if treatment_str and pd.notna(treatment_str) and str(treatment_str).strip() != '':
        # 使用 set 去重，避免重复噬菌体名称导致重复关系
        phage_names = list(set([x.strip() for x in str(treatment_str).split(',') if x.strip()]))
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

    # 4. 建立 HAS_ISOLATE → HostStrain（必须从 CSV 提供真实菌株）
    host_strain_label = data.get('host_strain')
    if not host_strain_label or pd.isna(host_strain_label) or str(host_strain_label).strip() == '':
        raise ValueError(f"病例 {case_id} 缺少 host_strain（真实菌株编号），无法建立 HAS_ISOLATE 关系，请补充数据后重试。")
    
    host_strain_id = _get_or_create_host_strain(tx, host_strain_label)
    
    # 关联 HostStrain 到 Pathogen
    tx.run("""
        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
        MATCH (p:Pathogen {pathogen_id: $pathogen_id})
        MERGE (h)-[:IS_STRAIN_OF]->(p)
    """, host_strain_id=host_strain_id, pathogen_id=data["pathogen_id"])
    
    # 建立 ClinicalCase → HAS_ISOLATE
    tx.run("""
        MATCH (c:ClinicalCase {case_id: $case_id})
        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
        MERGE (c)-[:HAS_ISOLATE]->(h)
    """, case_id=case_id, host_strain_id=host_strain_id)
    
    return case_id

def load_cases_from_csv(csv_path):
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条病例记录")
    
    # 检查是否有 host_strain 列（必须存在）
    if 'host_strain' not in df.columns:
        print("❌ CSV 文件中缺少 'host_strain' 列，该列是建立 HAS_ISOLATE 关系所必需的，请添加该列并填入真实菌株编号。")
        return 0  # 终止导入
    
    with get_driver() as driver:
        success_count = 0
        skip_count = 0
        with driver.session() as session:
            for index, row in df.iterrows():
                missing = validate_case_row(row)
                if missing:
                    print(f"⚠️ 第 {index+2} 行 (Case: {row.get('case_id', '未知')}) 缺失必填字段: {missing}，已跳过")
                    skip_count += 1
                    continue
                
                row_dict = row.to_dict()
                row_dict["resistance_genes"] = str(row_dict.get("resistance_genes", ""))
                optional_fields = [
                    'phage_treatment', 'microbiological_outcome', 'curated_by', 'curation_date',
                    'patient_age_group', 'comorbidities', 'prior_antibiotics',
                    'host_strain'  # 必须字段，已在 CSV 中校验存在
                ]
                for field in optional_fields:
                    if pd.isna(row_dict.get(field)):
                        row_dict[field] = None
                if row_dict.get('comorbidities') and isinstance(row_dict['comorbidities'], str):
                    row_dict['comorbidities'] = [x.strip() for x in row_dict['comorbidities'].split(',') if x.strip()]
                if row_dict.get('prior_antibiotics') and isinstance(row_dict['prior_antibiotics'], str):
                    row_dict['prior_antibiotics'] = [x.strip() for x in row_dict['prior_antibiotics'].split(',') if x.strip()]
                
                try:
                    session.execute_write(insert_clinical_case, row_dict)
                    success_count += 1
                except ValueError as e:
                    print(f"⚠️ {e}，已跳过该病例")
                    skip_count += 1
                except Exception as e:
                    print(f"❌ 导入失败 (Case: {row_dict.get('case_id')}): {e}")
                    skip_count += 1
    print(f"\n🎯 导入完成！成功 {success_count} 例，跳过 {skip_count} 例（含缺少 host_strain 或必填字段）。")
    return success_count

# ================== 噬菌体互作数据导入（新模型：LysisAssay + HostStrain） ==================
def load_phages_from_csv(csv_path):
    """从 CSV 导入 Phage 和互作数据，创建 LysisAssay、HostStrain 并关联 SourceArtifact（替代 EvidenceSource）"""
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
                    # 1. 创建或更新 Phage
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

                    # 2. 处理 evidence_ref 为列表
                    evidence_ref_str = row.get('evidence_ref', '')
                    if pd.isna(evidence_ref_str) or str(evidence_ref_str).strip() == '':
                        evidence_ref_list = []
                    else:
                        evidence_ref_list = [x.strip() for x in str(evidence_ref_str).split(',') if x.strip()]

                    # 3. 解析宿主菌株（优先从 host_strain 列读取，否则从 notes 解析）
                    host_strain_label = None
                    if 'host_strain' in df.columns and pd.notna(row.get('host_strain')) and str(row.get('host_strain')).strip():
                        host_strain_label = str(row['host_strain']).strip()
                    if not host_strain_label and row.get('notes') and pd.notna(row.get('notes')):
                        host_strain_label = _parse_host_strain_from_notes(row['notes'])

                    # 4. 创建 LysisAssay 节点
                    assay_id = f"ASSAY-{row['phage_id']}_{row['pathogen_id']}_{host_strain_label or 'UNKNOWN'}"
                    check = session.run("MATCH (a:LysisAssay {assay_id: $assay_id}) RETURN a", assay_id=assay_id).single()
                    if check:
                        print(f"   ⏭️ 跳过已存在的互作: {assay_id}")
                        success_count += 1
                        continue

                    session.run("""
                        MATCH (ph:Phage {phage_id: $phage_id})
                        CREATE (a:LysisAssay {
                            assay_id: $assay_id,
                            pathogen_id: $pathogen_id,
                            result: $infection_result,
                            result_value: $infection_probability,
                            evidence_level: $evidence_level,
                            evidence_ref: $evidence_ref,
                            qc_status: 'pending',
                            created_at: datetime()
                        })
                        CREATE (ph)-[:USED_IN]->(a)
                        RETURN a.assay_id AS aid
                    """,
                    phage_id=row['phage_id'],
                    pathogen_id=row['pathogen_id'],
                    assay_id=assay_id,
                    infection_result=row.get('infection_result') if pd.notna(row.get('infection_result')) else None,
                    infection_probability=float(row['infection_probability']) if pd.notna(row.get('infection_probability')) else None,
                    evidence_level=row['evidence_level'] if pd.notna(row.get('evidence_level')) else None,
                    evidence_ref=evidence_ref_list)

                    # 5. 关联 HostStrain（如果存在）
                    if host_strain_label:
                        host_strain_id = _get_or_create_host_strain(session, host_strain_label)
                        session.run("""
                            MATCH (a:LysisAssay {assay_id: $assay_id})
                            MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                            CREATE (a)-[:TESTED_AGAINST]->(h)
                        """, assay_id=assay_id, host_strain_id=host_strain_id)
                        # 建立 HostStrain → Pathogen 关系
                        session.run("""
                            MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                            MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                            MERGE (h)-[:IS_STRAIN_OF]->(p)
                        """, host_strain_id=host_strain_id, pathogen_id=row['pathogen_id'])

                    # 6. 关联 SourceArtifact（替代 EvidenceSource），使用 DERIVED_FROM 关系
                    for ref in evidence_ref_list:
                        if ref and str(ref).strip():
                            source_type = "literature" if ref.startswith("PMID") else "clinical_case"
                            source_id = _get_or_create_source_artifact(
                                session,
                                source_ref=ref,
                                source_type=source_type,
                                source_domain="scientific",
                                title=ref,
                                access_level="internal"
                            )
                            session.run("""
                                MATCH (a:LysisAssay {assay_id: $assay_id})
                                MATCH (s:SourceArtifact {source_id: $source_id})
                                CREATE (a)-[:DERIVED_FROM]->(s)
                            """, assay_id=assay_id, source_id=source_id)

                    success_count += 1
                    if success_count % 10 == 0:
                        print(f"   已处理 {success_count} 条互作...")

                except Exception as e:
                    print(f"   ❌ 导入失败 (第 {index+2} 行): {e}")

        print(f"\n🎯 噬菌体互作导入完成！成功 {success_count} 条记录。")

# ================== 从裂解谱 CSV 导入（新模型） ==================
def load_phages_from_lysis_csv(csv_path: str, pathogen_id: str = "PATH-003") -> dict:
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

    # 确保 Pathogen 存在
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

                # 创建或更新 Phage
                session.run("""
                    MERGE (ph:Phage {phage_id: $phage_id})
                    SET ph.name = $phage_name
                """, phage_id=phage_id, phage_name=phage_name)

                for host in host_cols:
                    if row[host] == 1:
                        total_positive += 1
                        host_strain_label = host.strip()
                        host_strain_id = _get_or_create_host_strain(session, host_strain_label)
                        assay_id = f"ASSAY-{phage_id}_{pathogen_id}_{host_strain_label.replace('-', '_')}"
                        existing = session.run("MATCH (a:LysisAssay {assay_id: $assay_id}) RETURN a", assay_id=assay_id).single()
                        if existing:
                            continue

                        evidence_ref = ["合作方裂解谱数据"]
                        session.run("""
                            MATCH (ph:Phage {phage_id: $phage_id})
                            CREATE (a:LysisAssay {
                                assay_id: $assay_id,
                                pathogen_id: $pathogen_id,
                                result: 'Lytic',
                                result_value: 1.0,
                                evidence_level: 'L2',
                                evidence_ref: $evidence_ref,
                                qc_status: 'pending',
                                created_at: datetime()
                            })
                            CREATE (ph)-[:USED_IN]->(a)
                            WITH a
                            MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                            CREATE (a)-[:TESTED_AGAINST]->(h)
                        """,
                        phage_id=phage_id,
                        pathogen_id=pathogen_id,
                        assay_id=assay_id,
                        evidence_ref=evidence_ref,
                        host_strain_id=host_strain_id)

                        # 建立 HostStrain → Pathogen 关系
                        session.run("""
                            MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                            MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                            MERGE (h)-[:IS_STRAIN_OF]->(p)
                        """, host_strain_id=host_strain_id, pathogen_id=pathogen_id)

                        # 关联 SourceArtifact（替代 EvidenceSource），使用 DERIVED_FROM 关系
                        source_id = _get_or_create_source_artifact(
                            session,
                            source_ref="合作方裂解谱数据",
                            source_type="lysis_assay_file",
                            source_domain="scientific",
                            title="合作方裂解谱数据",
                            access_level="internal"
                        )
                        session.run("""
                            MATCH (a:LysisAssay {assay_id: $assay_id})
                            MATCH (s:SourceArtifact {source_id: $source_id})
                            CREATE (a)-[:DERIVED_FROM]->(s)
                        """, assay_id=assay_id, source_id=source_id)

                        success_count += 1
                        if success_count % 100 == 0:
                            print(f"   已处理 {success_count} 条互作...")

    print(f"\n🎯 导入完成：")
    print(f"   - 噬菌体数: {len(phages_set)} 个")
    print(f"   - 阳性互作记录: {total_positive} 条")
    print(f"   - 成功插入: {success_count} 条")

    with get_driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (a:LysisAssay) RETURN count(a) AS total")
            total = result.single()["total"]

    return {
        "total_phages": len(phages_set),
        "positive_interactions": total_positive,
        "total_in_db": total
    }

def load_phages_from_lysis_csv_simple(csv_path: str = "../data/肺克数据脱敏.csv") -> dict:
    return load_phages_from_lysis_csv(csv_path, pathogen_id="PATH-003")

# ================== 市场情报子网导入（占位） ==================
def load_organizations_from_csv(csv_path: str) -> int:
    """
    从 CSV 导入 Organization 节点（竞争对手/机构）
    CSV 需包含字段：organization_id, canonical_name, aliases, organization_type, headquarters_country, website, company_status, public_or_private, description, review_status
    """
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条组织记录")
    count = 0
    with get_driver() as driver:
        with driver.session() as session:
            for _, row in df.iterrows():
                try:
                    aliases = row.get('aliases', '')
                    if pd.notna(aliases) and aliases:
                        aliases = [x.strip() for x in str(aliases).split(',') if x.strip()]
                    else:
                        aliases = []
                    session.run("""
                        MERGE (o:Organization {organization_id: $organization_id})
                        SET o.canonical_name = $canonical_name,
                            o.aliases = $aliases,
                            o.organization_type = $organization_type,
                            o.headquarters_country = $headquarters_country,
                            o.website = $website,
                            o.company_status = $company_status,
                            o.public_or_private = $public_or_private,
                            o.description = $description,
                            o.review_status = $review_status,
                            o.last_verified_at = datetime(),
                            o.created_at = coalesce(o.created_at, datetime())
                    """,
                    organization_id=row['organization_id'],
                    canonical_name=row['canonical_name'],
                    aliases=aliases,
                    organization_type=row.get('organization_type', 'biotech'),
                    headquarters_country=row.get('headquarters_country'),
                    website=row.get('website'),
                    company_status=row.get('company_status', 'active'),
                    public_or_private=row.get('public_or_private', 'unknown'),
                    description=row.get('description'),
                    review_status=row.get('review_status', 'pending')
                    )
                    count += 1
                except Exception as e:
                    print(f"   ❌ 导入组织失败: {e}")
    print(f"✅ 成功导入 {count} 个组织")
    return count

def load_intelligence_events_from_csv(csv_path: str) -> int:
    """
    导入 IntelligenceEvent 节点
    CSV 字段：event_id, event_type, title, event_date, published_at, factual_summary, organization_id (可关联), program_id (可关联), confidence, materiality, review_status
    """
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条事件记录")
    count = 0
    with get_driver() as driver:
        with driver.session() as session:
            for _, row in df.iterrows():
                try:
                    # 创建事件
                    session.run("""
                        MERGE (e:IntelligenceEvent {event_id: $event_id})
                        SET e.event_type = $event_type,
                            e.title = $title,
                            e.event_date = $event_date,
                            e.published_at = $published_at,
                            e.factual_summary = $factual_summary,
                            e.confidence = $confidence,
                            e.materiality = $materiality,
                            e.review_status = $review_status,
                            e.discovered_at = coalesce(e.discovered_at, datetime()),
                            e.created_at = coalesce(e.created_at, datetime())
                    """,
                    event_id=row['event_id'],
                    event_type=row['event_type'],
                    title=row['title'],
                    event_date=row.get('event_date') if pd.notna(row.get('event_date')) else None,
                    published_at=row.get('published_at') if pd.notna(row.get('published_at')) else None,
                    factual_summary=row['factual_summary'],
                    confidence=row.get('confidence', 'medium'),
                    materiality=row.get('materiality', 'medium'),
                    review_status=row.get('review_status', 'pending')
                    )

                    # 关联 Organization（若提供）
                    org_id = row.get('organization_id')
                    if org_id and pd.notna(org_id):
                        session.run("""
                            MATCH (e:IntelligenceEvent {event_id: $event_id})
                            MATCH (o:Organization {organization_id: $org_id})
                            CREATE (e)-[:CONCERNS]->(o)
                        """, event_id=row['event_id'], org_id=org_id)

                    # 关联 Program（若提供）
                    prog_id = row.get('program_id')
                    if prog_id and pd.notna(prog_id):
                        session.run("""
                            MATCH (e:IntelligenceEvent {event_id: $event_id})
                            MATCH (d:DevelopmentProgram {program_id: $prog_id})
                            CREATE (e)-[:AFFECTS]->(d)
                        """, event_id=row['event_id'], prog_id=prog_id)

                    count += 1
                except Exception as e:
                    print(f"   ❌ 导入事件失败: {e}")
    print(f"✅ 成功导入 {count} 个情报事件")
    return count

def load_development_programs_from_csv(csv_path: str) -> int:
    """导入 DevelopmentProgram（研发管线）"""
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条研发项目记录")
    count = 0
    with get_driver() as driver:
        with driver.session() as session:
            for _, row in df.iterrows():
                try:
                    aliases = row.get('aliases', '')
                    if pd.notna(aliases) and aliases:
                        aliases = [x.strip() for x in str(aliases).split(',') if x.strip()]
                    else:
                        aliases = []
                    session.run("""
                        MERGE (d:DevelopmentProgram {program_id: $program_id})
                        SET d.canonical_name = $canonical_name,
                            d.aliases = $aliases,
                            d.program_type = $program_type,
                            d.development_stage = $development_stage,
                            d.program_status = $program_status,
                            d.modality = $modality,
                            d.start_date = $start_date,
                            d.review_status = $review_status,
                            d.created_at = coalesce(d.created_at, datetime())
                    """,
                    program_id=row['program_id'],
                    canonical_name=row['canonical_name'],
                    aliases=aliases,
                    program_type=row.get('program_type', 'therapeutic'),
                    development_stage=row.get('development_stage', 'discovery'),
                    program_status=row.get('program_status', 'active'),
                    modality=row.get('modality'),
                    start_date=row.get('start_date') if pd.notna(row.get('start_date')) else None,
                    review_status=row.get('review_status', 'pending')
                    )
                    # 关联 Organization（如果指定）
                    org_id = row.get('organization_id')
                    if org_id and pd.notna(org_id):
                        session.run("""
                            MATCH (d:DevelopmentProgram {program_id: $program_id})
                            MATCH (o:Organization {organization_id: $org_id})
                            CREATE (o)-[:DEVELOPS]->(d)
                        """, program_id=row['program_id'], org_id=org_id)
                    count += 1
                except Exception as e:
                    print(f"   ❌ 导入研发项目失败: {e}")
    print(f"✅ 成功导入 {count} 个研发项目")
    return count

# ================== 清空数据库 ==================
def clear_database():
    print("⚠️  正在清空数据库...")
    with get_driver() as driver:
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
    print("✅ 数据库已清空")

# ================== 黄金配型（保持不变） ==================
def import_golden_rules() -> str:
    from src.scientific.import_service import get_driver
    validated_rules = [
        {
            "rule_id": "RULE_CRAB_KL2",
            "pathogen_species": "Acinetobacter baumannii",
            "strain_type": "KL2",
            "phage_name": "ΦK2-v3",
            "treatment": "ΦK2-v3 单用",
            "outcome": "第14天微生物清除，第6个月未复发",
            "evidence_from": "肖易倍团队第N次配型"
        },
        {
            "rule_id": "RULE_CRKP_KL47",
            "pathogen_species": "Klebsiella pneumoniae",
            "strain_type": "KL47",
            "phage_name": "ΦK47-w7",
            "treatment": "ΦK47-w7 + 碳青霉烯类",
            "outcome": "第3个月未复发",
            "evidence_from": "肖易倍团队第N次配型"
        },
        {
            "rule_id": "RULE_ECOLI_O25",
            "pathogen_species": "Escherichia coli",
            "strain_type": "O25",
            "phage_name": "CP-p-EC-23086",
            "treatment": "膀胱灌注（局部递送）",
            "outcome": "48小时内细菌计数断崖式下降",
            "evidence_from": "临床验证（结合CASE-001及既往数据）"
        }
    ]
    success_count = 0
    with get_driver() as driver:
        with driver.session() as session:
            for rule in validated_rules:
                result = session.run("""
                    MERGE (r:KnowledgeRule {rule_id: $rule_id})
                    SET r.strain_type = $strain_type,
                        r.treatment = $treatment,
                        r.outcome = $outcome,
                        r.evidence_from = $evidence_from
                    WITH r
                    MERGE (p:Pathogen {species: $pathogen_species})
                    ON CREATE SET p.resistance_mechanism = 'Unknown'
                    MERGE (p)-[:HAS_VALIDATED_RULE]->(r)
                    WITH r
                    MERGE (ph:Phage {name: $phage_name})
                    ON CREATE SET ph.family = 'Unknown'
                    MERGE (r)-[:RECOMMENDS_PHAGE]->(ph)
                    RETURN r.rule_id AS id
                """,
                rule_id=rule["rule_id"],
                pathogen_species=rule["pathogen_species"],
                strain_type=rule["strain_type"],
                phage_name=rule["phage_name"],
                treatment=rule["treatment"],
                outcome=rule["outcome"],
                evidence_from=rule["evidence_from"])
                if result.single():
                    success_count += 1
    return f"✅ 成功导入 {success_count} 条黄金规则"

# ================== 主入口 ==================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入病例和噬菌体数据（新模型）")
    parser.add_argument("--clear", action="store_true", help="清空数据库再导入")
    args = parser.parse_args()

    if args.clear:
        clear_database()
    
    print("\n===== 开始导入噬菌体互作 =====")
    load_phages_from_csv(config.PHAGE_CSV)

    print("\n===== 开始导入临床病例 =====")
    load_cases_from_csv(config.CASES_CSV)

    print("\n===== 开始导入裂解谱数据（新模型） =====")
    result = load_phages_from_lysis_csv_simple()
    print(result)
    
    print("\n🎉 所有数据导入完成！")