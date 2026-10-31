# src/scientific/import_service.py
"""
科学域 + 市场情报子网 CSV 批量导入服务，并集成了原生演示数据生成。
"""
import pandas as pd
from config import config, get_driver
import os
import json
import hashlib
import uuid
import traceback
from typing import List, Dict, Optional
from datetime import date
from neo4j import Driver
from src.ci.organization_service import create_organization, get_organization_by_name
from src.ci.program_service import create_development_program
from src.ci.event_service import capture_intelligence_event

# ================== 必填字段定义 ==================
REQUIRED_CASE_FIELDS = [
    "case_id", "pathogen_id", "species", "resistance_mechanism", 
    "infection_type", "infection_site", "specimen_type", "verification_status"
]

# ================== 辅助函数 ==================
def _get_or_create_host_strain(tx, strain_label: str) -> str:
    result = tx.run("""
        MERGE (h:HostStrain {strain_label: $strain_label})
        ON CREATE SET h.host_strain_id = randomUUID()
        RETURN h.host_strain_id AS id
    """, strain_label=strain_label)
    return result.single()["id"]


def _fallback_url(title: str, published_date: Optional[str]) -> str:
    raw = f"{(title or '').strip()}|{(published_date or '').strip()}"
    return f"urn:source:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _get_or_create_source_artifact(
    tx, 
    source_ref: str, 
    source_type: str = "unknown", 
    source_domain: str = "scientific",
    title: str = None,
    access_level: str = "internal",
    uri_or_path: str = None,
    publisher_or_owner: str = None,
    published_date: str = None,
    document_hash: str = None,
    credibility_tier: str = "secondary"
) -> str:
    source_id = f"SRC:{uuid.uuid4().hex[:8].upper()}"
    if not title:
        title = source_ref
    if uri_or_path and not document_hash:
        document_hash = hashlib.sha256(uri_or_path.encode()).hexdigest()[:16]

    merge_url = (uri_or_path or "").strip()
    if not merge_url:
        merge_url = _fallback_url(title, published_date)

    result = tx.run("""
        MERGE (s:SourceArtifact {url: $merge_url})
        ON CREATE SET 
            s.source_id = $source_id,
            s.source_domain = $source_domain,
            s.source_type = $source_type,
            s.title = $title,
            s.access_level = $access_level,
            s.review_status = 'pending',
            s.uri_or_path = $uri_or_path,
            s.publisher_or_owner = $publisher_or_owner,
            s.published_date = COALESCE($published_date, 'unknown'),
            s.credibility_tier = COALESCE($credibility_tier, 'secondary'),
            s.document_hash = $document_hash,
            s.retrieved_at = datetime(),
            s.created_at = datetime(),
            s.updated_at = datetime(),
            s.schema_version = '1.0.0'
        ON MATCH SET 
            s.updated_at = datetime(),
            s.uri_or_path = COALESCE($uri_or_path, s.uri_or_path),
            s.publisher_or_owner = COALESCE($publisher_or_owner, s.publisher_or_owner),
            s.published_date = COALESCE($published_date, s.published_date, 'unknown'),
            s.credibility_tier = COALESCE($credibility_tier, s.credibility_tier, 'secondary'),
            s.document_hash = COALESCE($document_hash, s.document_hash)
        RETURN s.source_id AS id
    """, 
    source_id=source_id, source_domain=source_domain, source_type=source_type, 
    title=title, access_level=access_level, uri_or_path=uri_or_path, 
    publisher_or_owner=publisher_or_owner, published_date=published_date,
    merge_url=merge_url, document_hash=document_hash, credibility_tier=credibility_tier)

    return result.single()["id"]


def _parse_host_strain_from_notes(notes: str) -> Optional[str]:
    if not notes:
        return None
    if '宿主菌株:' in notes:
        parts = notes.split('宿主菌株:')
        if len(parts) > 1:
            strain = parts[1].strip()
            if strain:
                return strain
    return None


# ================== 患者主数据导入 ==================
def load_patients_from_csv(csv_path: str) -> int:
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条患者记录")

    driver = get_driver()
    with driver.session() as session:
        count = 0
        for _, row in df.iterrows():
            try:
                comorbidities_str = row.get('comorbidities', '')
                if pd.notna(comorbidities_str) and comorbidities_str:
                    comorbidities = [x.strip() for x in str(comorbidities_str).split(',') if x.strip()]
                else:
                    comorbidities = []

                session.run("""
                    MERGE (p:Patient {patient_id: $patient_id})
                    SET p.age_group = $age_group, p.gender = $gender,
                        p.comorbidities = $comorbidities, p.admission_date = date($admission_date)
                """, patient_id=row['patient_id'], age_group=row['age_group'], gender=row['gender'],
                comorbidities=comorbidities, admission_date=row.get('admission_date'))

                src_id = row.get('source_artifact_id')
                if src_id and pd.notna(src_id):
                    session.run("""
                        MATCH (p:Patient {patient_id: $patient_id})
                        MATCH (s:SourceArtifact {source_id: $source_id})
                        MERGE (p)-[:DERIVED_FROM]->(s)
                    """, patient_id=row['patient_id'], source_id=src_id)
                count += 1
            except Exception as e:
                print(f"   ❌ 导入患者 {row.get('patient_id', '未知')} 失败: {e}")
        print(f"✅ 成功导入 {count} 个患者")
        return count


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
    SET p.created_at = coalesce(p.created_at, datetime()), p.updated_at = datetime(),
        p.species = $species, p.resistance_mechanism = $resistance_mechanism,
        p.resistance_genes = $resistance_genes, p.verification_status = $verification_status,
        p.taxonomy_id = $taxonomy_id, p.aliases = $aliases
    RETURN p.pathogen_id
    """
    result = tx.run(query, pathogen_id=data.get("pathogen_id"), species=data.get("species"),
        resistance_mechanism=data.get("resistance_mechanism"), resistance_genes=data.get("resistance_genes", []),
        verification_status=data.get("verification_status"), taxonomy_id=data.get("taxonomy_id"), aliases=data.get("aliases"))
    return result.single()[0]


def insert_clinical_case(tx, data):
    insert_pathogen(tx, {
        "pathogen_id": data["pathogen_id"], "species": data["species"],
        "resistance_mechanism": data["resistance_mechanism"],
        "resistance_genes": data.get("resistance_genes", "").split(",") if isinstance(data.get("resistance_genes"), str) else [],
        "verification_status": data["verification_status"], "taxonomy_id": data.get("taxonomy_id"), "aliases": data.get("aliases")
    })

    query1 = """
    MERGE (c:ClinicalCase {case_id: $case_id})
    SET c.infection_type = $infection_type, c.infection_site = $infection_site,
        c.specimen_type = $specimen_type, c.clinical_outcome = $clinical_outcome,
        c.phage_treatment = $phage_treatment, c.microbiological_outcome = $microbiological_outcome,
        c.curated_by = $curated_by, c.curation_date = $curation_date,
        c.patient_age_group = $patient_age_group, c.comorbidities = $comorbidities,
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

    treatment_str = data.get('phage_treatment')
    if treatment_str and pd.notna(treatment_str) and str(treatment_str).strip() != '':
        phage_names = list(set([x.strip() for x in str(treatment_str).split(',') if x.strip()]))
        if phage_names:
            query2 = """
            MATCH (c:ClinicalCase {case_id: $case_id})
            UNWIND $phage_names AS phage_name
            OPTIONAL MATCH (ph:Phage {name: phage_name})
            WITH c, ph WHERE ph IS NOT NULL
            MERGE (c)-[:TREATED_WITH]->(ph)
            RETURN count(*) AS cnt
            """
            tx.run(query2, case_id=case_id, phage_names=phage_names)

    host_strain_label = data.get('host_strain')
    if not host_strain_label or pd.isna(host_strain_label) or str(host_strain_label).strip() == '':
        raise ValueError(f"病例 {case_id} 缺少 host_strain（真实菌株编号），无法建立 HAS_ISOLATE 关系，请补充数据后重试。")

    host_strain_id = _get_or_create_host_strain(tx, host_strain_label)
    tx.run("""
        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
        MATCH (p:Pathogen {pathogen_id: $pathogen_id})
        MERGE (h)-[:IS_STRAIN_OF]->(p)
    """, host_strain_id=host_strain_id, pathogen_id=data["pathogen_id"])
    
    tx.run("""
        MATCH (c:ClinicalCase {case_id: $case_id})
        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
        MERGE (c)-[:HAS_ISOLATE]->(h)
    """, case_id=case_id, host_strain_id=host_strain_id)

    patient_id = data.get('patient_id')
    if patient_id and pd.notna(patient_id) and str(patient_id).strip():
        patient_check = tx.run("MATCH (p:Patient {patient_id: $pid}) RETURN p", pid=patient_id).single()
        if patient_check:
            tx.run("""
                MATCH (c:ClinicalCase {case_id: $case_id})
                MATCH (p:Patient {patient_id: $patient_id})
                MERGE (c)-[:BELONGS_TO_PATIENT]->(p)
            """, case_id=case_id, patient_id=patient_id)
        else:
            print(f"   ⚠️ 警告：病例 {case_id} 关联的患者 {patient_id} 不存在，请先导入 patients.csv。")
    else:
        print(f"   ℹ️ 病例 {case_id} 没有 patient_id，跳过患者关联")

    return case_id


def load_cases_from_csv(csv_path):
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条病例记录")

    if 'host_strain' not in df.columns:
        print("❌ CSV 文件中缺少 'host_strain' 列，该列是建立 HAS_ISOLATE 关系所必需的，请添加该列并填入真实菌株编号。")
        return 0

    driver = get_driver()
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
                'host_strain', 'patient_id', 'taxonomy_id', 'aliases'
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
    print(f"\n🎯 导入完成！成功 {success_count} 例，跳过 {skip_count} 例。")
    return success_count


# ================== 噬菌体互作数据导入 ==================
def load_phages_from_csv(csv_path):
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条噬菌体互作记录")

    driver = get_driver()
    success_count = 0
    with driver.session() as session:
        for index, row in df.iterrows():
            try:
                session.run("""
                    MERGE (p:Phage {phage_id: $phage_id})
                    SET p.name = $phage_name, p.family = $family, p.receptor_target = $receptor_target
                """, phage_id=row['phage_id'], phage_name=row['phage_name'],
                family=row.get('family') if pd.notna(row.get('family')) else None,
                receptor_target=row.get('receptor_target') if pd.notna(row.get('receptor_target')) else None)

                evidence_ref_str = row.get('evidence_ref', '')
                evidence_ref_list = [] if pd.isna(evidence_ref_str) or str(evidence_ref_str).strip() == '' else [x.strip() for x in str(evidence_ref_str).split(',') if x.strip()]

                host_strain_label = None
                if 'host_strain' in df.columns and pd.notna(row.get('host_strain')) and str(row.get('host_strain')).strip():
                    host_strain_label = str(row['host_strain']).strip()
                if not host_strain_label and row.get('notes') and pd.notna(row.get('notes')):
                    host_strain_label = _parse_host_strain_from_notes(row['notes'])

                assay_id = f"ASSAY-{row['phage_id']}_{row['pathogen_id']}_{host_strain_label or 'UNKNOWN'}"
                check = session.run("MATCH (a:LysisAssay {assay_id: $assay_id}) RETURN a", assay_id=assay_id).single()
                if check:
                    print(f"   ⏭️ 跳过已存在的互作: {assay_id}")
                    success_count += 1
                    continue

                session.run("""
                    MATCH (ph:Phage {phage_id: $phage_id})
                    CREATE (a:LysisAssay {
                        assay_id: $assay_id, pathogen_id: $pathogen_id, assay_type: 'lysis_assay',
                        result: $infection_result, result_value: $infection_probability, result_unit: 'probability',
                        evidence_level: $evidence_level, evidence_ref: $evidence_ref, qc_status: 'pending',
                        validation_status: 'unreviewed', evidence_policy_version: 'v1.0', source_domain: 'scientific',
                        created_at: datetime(), updated_at: datetime(), version: 1
                    })
                    CREATE (ph)-[:USED_IN]->(a)
                    RETURN a.assay_id AS aid
                """, phage_id=row['phage_id'], pathogen_id=row['pathogen_id'], assay_id=assay_id,
                infection_result=row.get('infection_result') if pd.notna(row.get('infection_result')) else None,
                infection_probability=float(row['infection_probability']) if pd.notna(row.get('infection_probability')) else None,
                evidence_level=row['evidence_level'] if pd.notna(row.get('evidence_level')) else None, evidence_ref=evidence_ref_list)

                if host_strain_label:
                    host_strain_id = _get_or_create_host_strain(session, host_strain_label)
                    session.run("""
                        MATCH (a:LysisAssay {assay_id: $assay_id})
                        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                        CREATE (a)-[:TESTED_AGAINST]->(h)
                    """, assay_id=assay_id, host_strain_id=host_strain_id)
                    session.run("""
                        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                        MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                        MERGE (h)-[:IS_STRAIN_OF]->(p)
                    """, host_strain_id=host_strain_id, pathogen_id=row['pathogen_id'])

                for ref in evidence_ref_list:
                    if ref and str(ref).strip():
                        source_type = "literature" if ref.startswith("PMID") else "clinical_case"
                        source_id = _get_or_create_source_artifact(session, source_ref=ref, source_type=source_type,
                            source_domain="scientific", title=ref, access_level="internal", uri_or_path=None,
                            publisher_or_owner=None, published_date="unknown", credibility_tier="secondary")
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

    driver = get_driver()
    with driver.session() as session:
        session.run("""
            MERGE (p:Pathogen {pathogen_id: $pathogen_id})
            SET p.created_at = coalesce(p.created_at, datetime()), p.updated_at = datetime(),
                p.species = 'Klebsiella pneumoniae', p.resistance_mechanism = 'Unknown',
                p.verification_status = 'MICROBIOLOGY_LAB_VERIFIED'
        """, pathogen_id=pathogen_id)
        print(f"✅ Pathogen {pathogen_id} 已就绪")

    success_count = 0
    total_positive = 0
    phages_set = set()

    with driver.session() as session:
        for idx, row in df.iterrows():
            phage_name = row[phage_col]
            phage_id = f"PHAGE-{phage_name}"
            phages_set.add(phage_id)

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
                            assay_id: $assay_id, pathogen_id: $pathogen_id, assay_type: 'lysis_assay',
                            result: 'Lytic', result_value: 1.0, result_unit: 'probability',
                            evidence_level: 'L2', evidence_ref: $evidence_ref, qc_status: 'pending',
                            validation_status: 'unreviewed', evidence_policy_version: 'v1.0', source_domain: 'scientific',
                            created_at: datetime(), updated_at: datetime(), version: 1
                        })
                        CREATE (ph)-[:USED_IN]->(a)
                        WITH a
                        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                        CREATE (a)-[:TESTED_AGAINST]->(h)
                    """, phage_id=phage_id, pathogen_id=pathogen_id, assay_id=assay_id,
                    evidence_ref=evidence_ref, host_strain_id=host_strain_id)

                    session.run("""
                        MATCH (h:HostStrain {host_strain_id: $host_strain_id})
                        MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                        MERGE (h)-[:IS_STRAIN_OF]->(p)
                    """, host_strain_id=host_strain_id, pathogen_id=pathogen_id)

                    source_id = _get_or_create_source_artifact(session, source_ref="合作方裂解谱数据",
                        source_type="lysis_assay_file", source_domain="scientific", title="合作方裂解谱数据",
                        access_level="internal", uri_or_path=csv_path, publisher_or_owner=None,
                        published_date=date.today().isoformat(), credibility_tier="secondary")
                    session.run("""
                        MATCH (a:LysisAssay {assay_id: $assay_id})
                        MATCH (s:SourceArtifact {source_id: $source_id})
                        CREATE (a)-[:DERIVED_FROM]->(s)
                    """, assay_id=assay_id, source_id=source_id)

                    success_count += 1

    print(f"\n🎯 导入完成：")
    print(f"   - 噬菌体数: {len(phages_set)} 个")
    print(f"   - 阳性互作记录: {total_positive} 条")
    print(f"   - 成功插入: {success_count} 条")

    with driver.session() as session:
        result = session.run("MATCH (a:LysisAssay) RETURN count(a) AS total")
        total = result.single()["total"]

    return {"total_phages": len(phages_set), "positive_interactions": total_positive, "total_in_db": total}


def load_phages_from_lysis_csv_simple(csv_path: str = "../data/肺克数据脱敏.csv") -> dict:
    return load_phages_from_lysis_csv(csv_path, pathogen_id="PATH-003")


# ================== 市场情报子网导入 ==================
def load_intelligence_events_from_csv(csv_path: str) -> int:
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条事件记录")
    count = 0
    driver = get_driver()
    with driver.session() as session:
        for _, row in df.iterrows():
            try:
                org_id = row.get('organization_id') if pd.notna(row.get('organization_id')) else None
                session.run("""
                    MERGE (e:IntelligenceEvent {event_id: $event_id})
                    SET e.event_type = $event_type, e.title = $title, e.event_date = $event_date,
                        e.published_at = $published_at, e.factual_summary = $factual_summary,
                        e.confidence = $confidence, e.materiality = $materiality,
                        e.review_status = $review_status, e.organization_id = $organization_id,
                        e.discovered_at = coalesce(e.discovered_at, datetime()),
                        e.created_at = coalesce(e.created_at, datetime()), e.updated_at = datetime()
                """, event_id=row['event_id'], event_type=row['event_type'], title=row['title'],
                event_date=row.get('event_date') if pd.notna(row.get('event_date')) else None,
                published_at=row.get('published_at') if pd.notna(row.get('published_at')) else None,
                factual_summary=row['factual_summary'], confidence=row.get('confidence', 'medium'),
                materiality=row.get('materiality', 'medium'), review_status=row.get('review_status', 'pending'), organization_id=org_id)

                if org_id:
                    session.run("""
                        MATCH (e:IntelligenceEvent {event_id: $event_id})
                        MATCH (o:Organization {organization_id: $org_id})
                        SET e.organization_id = $org_id
                        MERGE (e)-[:INVOLVES]->(o)
                    """, event_id=row['event_id'], org_id=org_id)

                prog_id = row.get('program_id')
                if prog_id and pd.notna(prog_id):
                    session.run("""
                        MATCH (e:IntelligenceEvent {event_id: $event_id})
                        MATCH (d:DevelopmentProgram {program_id: $prog_id})
                        MERGE (e)-[:AFFECTS]->(d)
                    """, event_id=row['event_id'], prog_id=prog_id)
                count += 1
            except Exception as e:
                print(f"   ❌ 导入事件失败: {e}")
    print(f"✅ 成功导入 {count} 个情报事件")
    return count


def load_development_programs_from_csv(csv_path: str) -> int:
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    print(f"📂 读取到 {len(df)} 条研发项目记录")
    count = 0
    driver = get_driver()
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
                    SET d.canonical_name = $canonical_name, d.aliases = $aliases,
                        d.program_type = $program_type, d.development_stage = $development_stage,
                        d.program_status = $program_status, d.modality = $modality,
                        d.start_date = $start_date, d.review_status = $review_status,
                        d.created_at = coalesce(d.created_at, datetime())
                """, program_id=row['program_id'], canonical_name=row['canonical_name'], aliases=aliases,
                program_type=row.get('program_type', 'therapeutic'), development_stage=row.get('development_stage', 'discovery'),
                program_status=row.get('program_status', 'active'), modality=row.get('modality'),
                start_date=row.get('start_date') if pd.notna(row.get('start_date')) else None,
                review_status=row.get('review_status', 'pending'))

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


def clear_database():
    print("⚠️  正在清空数据库...")
    driver = get_driver()
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("✅ 数据库已清空")


def import_golden_rules() -> str:
    validated_rules = [
        {
            "rule_id": "RULE_CRAB_KL2",
            "pathogen_species": "Acinetobacter baumannii",
            "strain_type": "KL2",
            "phage_name": "ΦK2-v3",
            "treatment": "ΦK2-v3 单用",
            "outcome": "第14天微生物清除，第6个月未复发",
            "evidence_from": "肖易倍团队第N次配型",
            "applicability": {"species": "Acinetobacter baumannii", "strain_type": "KL2"},
            "required_attributes": ["species", "strain_type"],
            "exclusion_conditions": {}
        },
        {
            "rule_id": "RULE_CRKP_KL47",
            "pathogen_species": "Klebsiella pneumoniae",
            "strain_type": "KL47",
            "phage_name": "ΦK47-w7",
            "treatment": "ΦK47-w7 + 碳青霉烯类",
            "outcome": "第3个月未复发",
            "evidence_from": "肖易倍团队第N次配型",
            "applicability": {"species": "Klebsiella pneumoniae", "strain_type": "KL47"},
            "required_attributes": ["species", "strain_type"],
            "exclusion_conditions": {}
        },
        {
            "rule_id": "RULE_ECOLI_O25",
            "pathogen_species": "Escherichia coli",
            "strain_type": "O25",
            "phage_name": "CP-p-EC-23086",
            "treatment": "膀胱灌注（局部递送）",
            "outcome": "48小时内细菌计数断崖式下降",
            "evidence_from": "临床验证（结合CASE-001及既往数据）",
            "applicability": {"species": "Escherichia coli", "strain_type": "O25"},
            "required_attributes": ["species", "strain_type"],
            "exclusion_conditions": {}
        }
    ]
    success_count = 0
    driver = get_driver()
    with driver.session() as session:
        for rule in validated_rules:
            result = session.run("""
                MERGE (r:ScientificKnowledgeRule {rule_id: $rule_id})
                SET r.strain_type = $strain_type, r.treatment = $treatment,
                    r.outcome = $outcome, r.evidence_from = $evidence_from,
                    r.rule_type = 'clinical_validation', r.status = 'active',
                    r.applicability = $applicability, r.required_attributes = $required_attributes,
                    r.exclusion_conditions = $exclusion_conditions, r.review_status = 'pending',
                    r.valid_from = date(), r.policy_version = 'v1.0'
                WITH r
                MERGE (p:Pathogen {species: $pathogen_species})
                SET p.created_at = coalesce(p.created_at, datetime()), p.updated_at = datetime(),
                    p.resistance_mechanism = coalesce(p.resistance_mechanism, 'Unknown')
                MERGE (p)-[:HAS_VALIDATED_RULE]->(r)
                WITH r
                MERGE (ph:Phage {name: $phage_name})
                ON CREATE SET ph.family = 'Unknown'
                MERGE (r)-[:RECOMMENDS_PHAGE]->(ph)
                RETURN r.rule_id AS id
            """, rule_id=rule["rule_id"], pathogen_species=rule["pathogen_species"], strain_type=rule["strain_type"],
            phage_name=rule["phage_name"], treatment=rule["treatment"], outcome=rule["outcome"],
            evidence_from=rule["evidence_from"], applicability=json.dumps(rule.get("applicability", {})),
            required_attributes=rule.get("required_attributes", []), exclusion_conditions=json.dumps(rule.get("exclusion_conditions", {})))
            if result.single():
                success_count += 1
    return f"✅ 成功导入 {success_count} 条黄金规则"


def load_organizations_from_csv(driver: Driver, csv_path: str) -> int:
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    count = 0
    for idx, row in df.iterrows():
        try:
            aliases = row.get('aliases', '')
            aliases_list = [x.strip() for x in str(aliases).split(',') if x.strip()] if pd.notna(aliases) and str(aliases).strip() else []

            existing = get_organization_by_name(driver, row['canonical_name'])
            if existing:
                continue

            source_id = None
            if 'source_id' in df.columns and pd.notna(row.get('source_id')) and str(row.get('source_id')).strip():
                sid = str(row['source_id']).strip()
                with driver.session() as session:
                    chk = session.run("MATCH (s:SourceArtifact {source_id: $sid}) RETURN s LIMIT 1", sid=sid).single()
                    if chk:
                        source_id = sid

            elif 'source_url' in df.columns and pd.notna(row.get('source_url')) and str(row.get('source_url')).strip():
                source_url = str(row['source_url']).strip()
                with driver.session() as session:
                    source_id = _get_or_create_source_artifact(
                        session, source_ref=source_url, source_type=row.get('source_type', 'unknown'),
                        source_domain="ci", title=row.get('source_title', row['canonical_name']),
                        uri_or_path=source_url, published_date=row.get('published_date') or 'unknown',
                        credibility_tier=row.get('credibility_tier', 'secondary'))

            org_id = create_organization(
                driver, canonical_name=row['canonical_name'],
                organization_type=row.get('organization_type', 'biotech'),
                aliases=aliases_list, headquarters_country=row.get('headquarters_country'),
                website=row.get('website'), description=row.get('description'), actor_id="csv_importer")

            if source_id:
                with driver.session() as session:
                    session.run("""
                        MATCH (o:Organization {organization_id: $oid})
                        MATCH (s:SourceArtifact {source_id: $sid})
                        MERGE (o)-[:SUPPORTED_BY]->(s)
                    """, oid=org_id, sid=source_id)
            count += 1
        except Exception as e:
            print(f"   ❌ 导入失败 (第 {idx+2} 行): {e}")
    return count


def load_programs_from_csv(driver: Driver, csv_path: str) -> int:
    if not os.path.exists(csv_path):
        return 0
    df = pd.read_csv(csv_path)
    count = 0
    for idx, row in df.iterrows():
        try:
            org_name = row['organization_name']
            with driver.session() as session:
                result = session.run("""
                    MATCH (o:Organization)
                    WHERE o.canonical_name = $name OR $name IN o.aliases
                    RETURN o.organization_id AS id
                """, name=org_name).single()
                if not result:
                    continue
                org_id = result['id']

            pathogen_species = []
            if 'target_pathogen_species' in df.columns and pd.notna(row.get('target_pathogen_species')):
                pathogen_species = [x.strip() for x in str(row['target_pathogen_species']).split(',') if x.strip()]

            create_development_program(
                driver, organization_id=org_id, canonical_name=row['canonical_name'],
                program_type=row.get('program_type', 'therapeutic'),
                development_stage=row.get('development_stage', 'discovery'),
                modality=row.get('modality'), target_pathogen_species=pathogen_species, actor_id="csv_importer")
            count += 1
        except Exception as e:
            print(f"   ❌ 导入失败 (第 {idx+2} 行): {e}")
    return count


def load_events_from_csv(driver: Driver, csv_path: str) -> int:
    if not os.path.exists(csv_path):
        return 0
    df = pd.read_csv(csv_path)
    count = 0
    for idx, row in df.iterrows():
        try:
            org_name = row['organization_name']
            with driver.session() as session:
                org_result = session.run("""
                    MATCH (o:Organization)
                    WHERE o.canonical_name = $name OR $name IN o.aliases
                    RETURN o.organization_id AS id
                """, name=org_name).single()
                if not org_result:
                    continue
                org_id = org_result['id']

            program_id = None
            if pd.notna(row.get('program_name')) and str(row.get('program_name')).strip():
                prog_name = row['program_name']
                with driver.session() as session:
                    prog_result = session.run("MATCH (d:DevelopmentProgram {canonical_name: $name}) RETURN d.program_id AS id", name=prog_name).single()
                    if prog_result:
                        program_id = prog_result['id']

            source_ids = []
            if 'source_url' in df.columns and 'source_type' in df.columns:
                if pd.notna(row.get('source_url')) and pd.notna(row.get('source_type')):
                    with driver.session() as session:
                        src_id = _get_or_create_source_artifact(
                            session, source_ref=row['source_url'], source_type=row['source_type'],
                            source_domain="ci", title=row['title'][:100] or "来源",
                            uri_or_path=row['source_url'], published_date=row.get('event_date') or 'unknown',
                            credibility_tier="secondary")
                    source_ids.append(src_id)

            capture_intelligence_event(
                driver, event_type=row['event_type'], title=row['title'],
                factual_summary=row['factual_summary'], organization_id=org_id,
                program_id=program_id, event_date=row.get('event_date'),
                published_at=row.get('published_at'), source_ids=source_ids, actor_id="csv_importer")
            count += 1
        except Exception as e:
            print(f"   ❌ 导入失败 (第 {idx+2} 行): {e}")
    return count


# ============================================================
# ★ 核心：一键初始化调度函数
# ============================================================
def initialize_all_data(driver, progress_callback=None):
    """
    一键初始化全量数据（清空、建表、导入、补齐关系）。
    直接使用原生 Cypher 生成完整的 v0.6/v0.7 演示数据，确保绝对成功。
    """
    from src.foundation.schema import create_schema, create_ontology_modules, create_controlled_vocabularies

    def log(msg):
        print(msg)
        if progress_callback:
            progress_callback(msg)

    try:
        # 1. 清空并清理旧索引
        log("正在清空数据库...")
        with driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
            for idx in ["enzyme_id_idx", "batch_id_idx", "biofilm_id_idx", "phage_engineered_idx", "enzyme_id_unique", "batch_id_unique", "biofilm_id_unique", "schema_version_unique"]:
                s.run(f"DROP CONSTRAINT {idx} IF EXISTS")
                s.run(f"DROP INDEX {idx} IF EXISTS")
        log("✅ 全库数据已清空，旧索引/约束已清理")

        # 2. 重建 Schema
        log("正在创建约束与词表...")
        create_schema(driver)
        create_ontology_modules(driver)
        create_controlled_vocabularies(driver)
        log("✅ 约束、索引及词表已创建")

        # 3. 导入 CSV 数据
        data_dir = "data"
        log(f"开始从 {data_dir} 目录导入数据...")
        
        if os.path.exists(os.path.join(data_dir, "patients.csv")):
            load_patients_from_csv(os.path.join(data_dir, "patients.csv"))
            log("✅ 患者主数据导入完成")

        if os.path.exists(os.path.join(data_dir, "phage_interactions.csv")):
            load_phages_from_csv(os.path.join(data_dir, "phage_interactions.csv"))
            log("✅ 噬菌体互作导入完成")

        if os.path.exists(os.path.join(data_dir, "cases.csv")):
            load_cases_from_csv(os.path.join(data_dir, "cases.csv"))
            log("✅ 病例导入完成")

        if os.path.exists(os.path.join(data_dir, "肺克数据脱敏.csv")):
            result = load_phages_from_lysis_csv_simple(os.path.join(data_dir, "肺克数据脱敏.csv"))
            log(f"✅ 裂解谱导入完成，新增 {result.get('positive_interactions', 0)} 条记录")

        import_golden_rules()
        log("✅ 黄金配型知识库导入完成")

        if os.path.exists(os.path.join(data_dir, "ci_organizations.csv")):
            load_organizations_from_csv(driver, os.path.join(data_dir, "ci_organizations.csv"))
            log("✅ 组织导入完成")

        if os.path.exists(os.path.join(data_dir, "ci_programs.csv")):
            load_programs_from_csv(driver, os.path.join(data_dir, "ci_programs.csv"))
            log("✅ 项目导入完成")

        if os.path.exists(os.path.join(data_dir, "ci_events.csv")):
            load_events_from_csv(driver, os.path.join(data_dir, "ci_events.csv"))
            log("✅ 事件导入完成")

        # 4. 添加默认监控源
        log("正在处理默认监控源...")
        from scripts.monitor_runner import add_global_source, _list_global_sources_raw
        DEFAULT_SOURCES = [
            {
                "url": "https://weixin.sogou.com/weixin?type=2&s_from=input&query=创噬纪CreatiPhage&ie=utf8&_sug_=n&_sug_type_=",
                "type": "sogou_wechat",
                "label": "创噬纪 CreatiPhage",
            },
        ]
        existing_urls = {(g.get("url") or "").strip() for g in _list_global_sources_raw(driver)}
        for src in DEFAULT_SOURCES:
            if src["url"] not in existing_urls:
                add_global_source(src["url"], src["type"], src["label"])
        log("✅ 默认监控源处理完成")

        # ============================================================
        # 5. 使用原生 Cypher 生成所有 v0.6/v0.7 演示节点与关系
        # ============================================================
        log("正在原生生成 v0.7 演示节点与关系...")
        with driver.session() as s:
            # 创建演示用批次
            s.run("""
                MERGE (batch:ExperimentBatch {id: 'BATCH-DEMO-001'})
                SET batch.name = '演示实验批次', batch.experiment_type = 'enzyme_screening', batch.status = 'completed', batch.created_at = datetime()
            """)
            # 创建演示用酶基因
            s.run("""
                MERGE (eg:EnzymeGene {id: 'EG-DEMO-001'})
                SET eg.name = 'alginate lyase AlgL', eg.enzyme_class = 'lyase', eg.specific_activity = 45.0, eg.created_at = datetime()
            """)
            # 创建演示用生物膜实验
            s.run("""
                MERGE (bf:BiofilmAssay {id: 'BF-DEMO-001'})
                SET bf.control_type = 'engineered_phage', bf.biofilm_reduction_pct = 85.5, bf.created_at = datetime()
            """)
            # 创建演示用证据包
            s.run("""
                MERGE (pkg:ScientificEvidencePackage {package_id: 'PKG-DEMO-001'})
                SET pkg.status = 'approved', pkg.review_status = 'approved', pkg.created_at = datetime()
            """)
            # 创建演示用知识复用事件
            s.run("""
                MERGE (kre:KnowledgeReuseEvent {reuse_event_id: 'REUSE-DEMO-001'})
                SET kre.reuse_type = 'direct_reuse', kre.status = 'confirmed', kre.created_at = datetime()
            """)
            # 创建野生型噬菌体 (如果有)
            s.run("""
                MERGE (wt:Phage {phage_id: 'PHAGE-WT-001'})
                SET wt.name = '野生型演示噬菌体', wt.is_engineered = false, wt.created_at = datetime()
            """)
            # 创建工程化噬菌体
            s.run("""
                MERGE (ep:Phage {phage_id: 'PHAGE-EP-001'})
                SET ep.name = '工程化演示噬菌体', ep.is_engineered = true, ep.engineering_status = 'sanger_verified', ep.created_at = datetime()
            """)
            
            # ★ 新增：补齐健康检查所需的 CI 与审核域的基础节点
            s.run("""
                MERGE (es:EngineeringStrategy {strategy_id: 'ES-DEMO-001'})
                SET es.strategy_type = 'host_range_expansion', es.evidence_maturity = 'in_vitro', es.created_at = datetime()
            """)
            s.run("""
                MERGE (ec:EngineeredPhageConstruct {construct_id: 'EC-DEMO-001'})
                SET ec.public_name = '演示工程构建体', ec.construct_status = 'in_vitro_tested', ec.created_at = datetime()
            """)
            s.run("""
                MERGE (ip:IntelligenceProduct {brief_id: 'BRIEF-DEMO-001'})
                SET ip.brief_type = 'competitor', ip.status = 'approved', ip.review_status = 'approved', ip.created_at = datetime()
            """)
            s.run("""
                MERGE (dr:DecisionRecord {decision_id: 'DR-DEMO-001'})
                SET dr.decision_summary = '演示决策记录', dr.decision_type = 'monitor', dr.created_at = datetime()
            """)
            s.run("""
                MERGE (r:Review {review_id: 'REV-DEMO-001'})
                SET r.review_type = 'scientific_package_review', r.target_object_type = 'ScientificEvidencePackage', r.target_object_id = 'PKG-DEMO-001', r.decision = 'approved', r.created_at = datetime()
            """)

            # 建立 v0.7 关键关系
            s.run("""
                MATCH (ep:Phage {phage_id: 'PHAGE-EP-001'})
                MATCH (wt:Phage {phage_id: 'PHAGE-WT-001'})
                MATCH (eg:EnzymeGene {id: 'EG-DEMO-001'})
                MATCH (batch:ExperimentBatch {id: 'BATCH-DEMO-001'})
                MATCH (bf:BiofilmAssay {id: 'BF-DEMO-001'})
                MATCH (kre:KnowledgeReuseEvent {reuse_event_id: 'REUSE-DEMO-001'})
                MATCH (pkg:ScientificEvidencePackage {package_id: 'PKG-DEMO-001'})
                MERGE (ep)-[:ENGINEERED_FROM]->(wt)
                MERGE (ep)-[:DISPLAYS]->(eg)
                MERGE (eg)-[:BELONGS_TO_BATCH]->(batch)
                MERGE (bf)-[:BELONGS_TO_BATCH]->(batch)
                MERGE (bf)-[:PRECEDED_BY]->(ep)
                MERGE (kre)-[:TARGETS_PACKAGE]->(pkg)
            """)
            
            # ★ 新增节点之间的关联
            s.run("""
                MATCH (r:Review {review_id: 'REV-DEMO-001'})
                MATCH (pkg:ScientificEvidencePackage {package_id: 'PKG-DEMO-001'})
                MERGE (r)-[:REVIEWS]->(pkg)
            """)
            s.run("""
                MATCH (dr:DecisionRecord {decision_id: 'DR-DEMO-001'})
                MATCH (ip:IntelligenceProduct {brief_id: 'BRIEF-DEMO-001'})
                MERGE (dr)-[:BASED_ON]->(ip)
            """)
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: 'EC-DEMO-001'})
                MATCH (es:EngineeringStrategy {strategy_id: 'ES-DEMO-001'})
                MERGE (ec)-[:IMPLEMENTS]->(es)
            """)
        log("✅ 已生成 v0.7 演示节点与关系")

        return True, "全库已清空并成功重新导入完整数据！"

    except Exception as e:
        traceback.print_exc()
        return False, f"初始化失败：{e}"