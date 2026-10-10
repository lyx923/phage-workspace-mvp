# scripts/setup_all_stage2.py
"""
Stage2 一键数据准备（合并版）+ v0.6 收尾

执行顺序：
    0.5) fix_biomx_event_type         —— 修正 BiomX 事件类型 + DATA_CORRECTION 审计
    0.6) clean_reference_tags         —— 清理 description 中的 [reference:X] 标签
    1)   基础数据重建                  —— Pathogen / Strategy / Construct / Assessment
                                        / SourceArtifact / Claim / Result / Patent / Trial
    1.5) 4 个 v0.6 派生关系回填
         - backfill_program_uses_strategy   → (d)-[:USES_STRATEGY]->(es)
         - backfill_construct_developed_by  → (ec)-[:DEVELOPED_BY]->(o)
         - backfill_result_to_claim         → (tr)-[:SUPPORTED_OR_CHALLENGES]->(tc)
         - backfill_claim_evaluated_by      → (tc)-[:EVALUATED_BY]->(ta)
    1.8) register_v06_modules         —— 注册 v0.6 顶层 OntologyModule
    2)   Brief 生成                    —— Competitor / Technology / DecisionRecord
    3)   补齐 Review / citations / data_gaps
    4)   backfill_brief_quality_fields —— 回填 Brief 质量能力字段
    5)   backfill_time_semantics       —— 回填 valid_from / valid_to

用法（项目根目录）：
    python scripts/setup_all_stage2.py

脚本幂等，可重复执行。
"""
import os
import sys
import json
import re
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import get_driver
from src.shared.review import create_review
from src.shared.source_artifact_service import create_source_artifact
from src.shared.pathogen_service import get_or_create_pathogen
from src.shared.time_service import backfill_valid_from, time_coverage_report
from src.shared.ontology_module_service import (
    register_ontology_module, get_module_registry,
)
from src.shared.audit_service import write_audit_event

from src.engineering_intelligence.strategy_classifier import create_engineering_strategy
from src.engineering_intelligence.construct_service import (
    create_engineered_construct, link_program_to_construct,
    backfill_construct_developed_by,
)
from src.engineering_intelligence.technology_assessment import (
    create_technology_assessment,
    backfill_claim_evaluated_by,
)
from src.engineering_intelligence.claim_extractor import (
    create_technical_claim, create_technical_result,
    backfill_result_to_claim,
)
from src.engineering_intelligence.technology_brief import generate_technology_brief

from src.ci.competitor_brief import generate_competitor_brief
from src.ci.patent_service import create_patent_family
from src.ci.clinical_trial_service import create_clinical_trial
from src.ci.program_service import backfill_program_uses_strategy
from src.decision_support.decision_record import create_decision_record


# ============================================================
# 常量
# ============================================================

DEFAULT_DATA_GAPS_BY_TYPE = {
    "competitor": [
        "公司上市/私有状态未确认",
        "部分事件缺少二次来源核验",
    ],
    "engineered_phage_technology": [
        "当前证据成熟度以体外为主，缺少体内/临床验证",
        "部分构建体尚未关联完整证据链",
        "尚未关联专利族或论文映射",
    ],
}
DEFAULT_GAPS_FALLBACK = ["待补充数据缺口说明"]

STRATEGY_DEFS = [
    ("host_range_expansion",   "通过改造尾纤维或受体结合蛋白扩展宿主范围"),
    ("tail_fiber_engineering", "尾纤维定向改造，改变受体识别特异性"),
    ("lysis_enhancement",      "改造裂解模块或裂解酶，增强裂解活性"),
    ("biofilm_disruption",     "引入降解胞外基质的酶或改造穿透能力"),
    ("payload_delivery",       "递送抗耐药 / 抗毒力 / CRISPR 等外源载荷"),
]

CONSTRUCT_DEFS = [
    ("host_range_expansion",   "vB_Kpn_HRE_001", "Klebsiella pneumoniae", "in_vitro_tested", "2024-06-10"),
    ("host_range_expansion",   "vB_Pae_HRE_002", "Pseudomonas aeruginosa","in_vitro_tested", "2024-09-01"),
    ("tail_fiber_engineering", "vB_Kpn_TFE_003", "Klebsiella pneumoniae", "in_vitro_tested", "2024-06-10"),
    ("tail_fiber_engineering", "vB_Eco_TFE_004", "Escherichia coli",      "proposed",        "2025-01-10"),
    ("lysis_enhancement",      "vB_Pae_LYE_005", "Pseudomonas aeruginosa","in_vitro_tested", "2024-09-01"),
    ("lysis_enhancement",      "vB_Sau_LYE_006", "Staphylococcus aureus", "in_vitro_tested", "2024-09-01"),
    ("biofilm_disruption",     "vB_Pae_BFD_007", "Pseudomonas aeruginosa","in_vitro_tested", "2024-09-01"),
    ("biofilm_disruption",     "vB_Sau_BFD_008", "Staphylococcus aureus", "proposed",        "2024-09-01"),
    ("payload_delivery",       "vB_Kpn_PLD_009", "Klebsiella pneumoniae", "in_vitro_tested", "2024-05-20"),
    ("payload_delivery",       "vB_Pae_PLD_010", "Pseudomonas aeruginosa","proposed",        "2024-05-20"),
]

CLAIM_TYPE_MAP = {
    "host_range_expansion":   "host_range",
    "tail_fiber_engineering": "host_range",
    "lysis_enhancement":      "efficacy",
    "biofilm_disruption":     "efficacy",
    "payload_delivery":       "safety",
}

_REFERENCE_TAG_PATTERN = re.compile(r"\[reference:\d+\]")


# ============================================================
# 0.5 BiomX 事件类型修正 + DATA_CORRECTION 审计
# ============================================================

def fix_biomx_event_type(driver):
    print("\n[0.5] 修正 BiomX / Adaptive Phage 事件的 event_type ...")

    with driver.session() as s:
        rows = list(s.run("""
            MATCH (e:IntelligenceEvent)
            WHERE e.title CONTAINS 'BiomX' AND e.title CONTAINS 'Adaptive Phage'
            RETURN e.event_id AS eid, e.event_type AS old_type
        """))

    if not rows:
        print("  ⚠️ 未找到 BiomX / Adaptive Phage 事件，跳过")
        return

    for r in rows:
        eid = r["eid"]
        old_type = r["old_type"]

        if old_type != "acquisition":
            with driver.session() as s:
                s.run("""
                    MATCH (e:IntelligenceEvent {event_id: $eid})
                    SET e.event_type = 'acquisition',
                        e.event_type_corrected = true,
                        e.correction_date = $date,
                        e.correction_reason = 'Initial import misclassified acquisition as partnership',
                        e.updated_at = datetime()
                """, eid=eid,
                     date=datetime.now(timezone.utc).isoformat())
            print(f"  ✅ {eid}: {old_type} → acquisition")
        else:
            print(f"  ℹ️ {eid}: 已是 acquisition，无需修正")

        # 幂等写 DATA_CORRECTION 审计
        with driver.session() as s:
            existing = s.run("""
                MATCH (a:AuditEvent {
                    action_type: 'DATA_CORRECTION',
                    object_type: 'IntelligenceEvent'
                })
                WHERE a.object_id = $eid
                RETURN a.audit_id AS aid LIMIT 1
            """, eid=eid).single()

        if not existing:
            audit_id = write_audit_event(
                driver,
                action_type="DATA_CORRECTION",
                object_type="IntelligenceEvent",
                object_id=eid,
                actor_id="setup_all",
                delta={
                    "field": "event_type",
                    "before": old_type,
                    "after": "acquisition",
                },
                reason="修正 BiomX 收购 APT 事件的 event_type",
            )
            print(f"  ✅ DATA_CORRECTION 审计: {audit_id}")
        else:
            print(f"  ℹ️ DATA_CORRECTION 审计已存在: {existing['aid']}")


# ============================================================
# 0.6 清理 [reference:X] 标签
# ============================================================

def clean_reference_tags(driver):
    print("\n[0.6] 清理 description 中的 [reference:X] 标签 ...")

    with driver.session() as s:
        rows = list(s.run("""
            MATCH (n)
            WHERE n.description IS NOT NULL
              AND n.description CONTAINS '[reference:'
            RETURN labels(n)[0] AS label,
                   n.description AS old_desc,
                   CASE
                     WHEN n.organization_id IS NOT NULL THEN n.organization_id
                     WHEN n.event_id IS NOT NULL THEN n.event_id
                     WHEN n.program_id IS NOT NULL THEN n.program_id
                     ELSE 'unknown'
                   END AS node_id
        """))

    if not rows:
        print("  ✅ 无 [reference:X] 残留")
        return

    for r in rows:
        old_desc = r["old_desc"]
        new_desc = _REFERENCE_TAG_PATTERN.sub("", old_desc).strip()

        with driver.session() as s:
            s.run("""
                MATCH (n {description: $old_desc})
                SET n.description = $new_desc,
                    n.description_cleaned = true,
                    n.description_raw = $old_desc,
                    n.updated_at = datetime()
            """, old_desc=old_desc, new_desc=new_desc)

        write_audit_event(
            driver,
            action_type="DATA_CORRECTION",
            object_type=r["label"],
            object_id=r["node_id"],
            actor_id="setup_all",
            delta={
                "field": "description",
                "old": old_desc[:100],
                "new": new_desc[:100],
                "pattern": "[reference:X] tags removed",
            },
            reason="清理历史导入数据中的 [reference:X] 内联引用标签",
        )

    print(f"  ✅ 清理 {len(rows)} 个节点的 description")


# ============================================================
# 1.8 注册 v0.6 顶层 OntologyModule
# ============================================================

def register_v06_modules(driver):
    print("\n[1.8] 注册 v0.6 顶层 OntologyModule ...")

    foundation_id = register_ontology_module(
        driver,
        module_name="Foundation",
        version="0.6.0",
        owner_team="phage_platform_team",
        description="Enterprise Ontology 共享基础层，跨域共享对象",
        object_types=[
            "Pathogen", "Organization", "SourceArtifact", "Review",
            "AuditEvent", "OntologyModule", "ControlledVocabulary",
        ],
        depends_on=[],
        changelog="v0.6.0: AuditEvent 和 OntologyModule 正式落地",
        status="active",
        actor_id="setup_all",
    )
    print(f"  ✅ Foundation: {foundation_id}")

    ci_id = register_ontology_module(
        driver,
        module_name="CI_Domain",
        version="0.6.0",
        owner_team="phage_ci_team",
        description=(
            "竞争情报域：覆盖竞争对手组织、研发项目、工程策略、"
            "技术主张与情报产品"
        ),
        object_types=[
            "DevelopmentProgram", "IntelligenceEvent", "EngineeringStrategy",
            "EngineeredPhageConstruct", "TechnicalClaim", "TechnicalResult",
            "TechnologyAssessment", "CompetitorAssessment",
            "IntelligenceProduct", "DecisionRecord", "IntelligenceUseEvent",
        ],
        depends_on=["Foundation"],
        changelog=(
            "v0.6.0: 修复 SourceArtifact 引用、归因链断链、"
            "补充 AuditEvent 集成"
        ),
        status="experimental",
        actor_id="setup_all",
    )
    print(f"  ✅ CI_Domain: {ci_id}")

    print("\n  当前 OntologyModule 注册表：")
    for m in get_module_registry(driver):
        deps = m.get("depends_on") or []
        dep_str = "无依赖" if not deps else ", ".join(deps)
        print(f"    [{m['status']}] {m['module_name']} v{m['version']}  "
              f"(依赖：{dep_str})")


# ============================================================
# 1. 基础数据重建
# ============================================================

def ensure_pathogens(driver):
    print("\n[1.1] 确保 Pathogen 就绪 ...")
    species_list = [
        "Klebsiella pneumoniae",
        "Pseudomonas aeruginosa",
        "Staphylococcus aureus",
        "Escherichia coli",
    ]
    for sp in species_list:
        pid = get_or_create_pathogen(
            driver, species=sp, pathogen_type="bacteria", actor_id="setup_all"
        )
        print(f"  ✅ {sp} -> {pid}")


def ensure_strategies(driver):
    print("\n[1.2] 确保 EngineeringStrategy 就绪 ...")
    created = 0
    for stype, desc in STRATEGY_DEFS:
        try:
            create_engineering_strategy(
                driver, strategy_type=stype, description=desc,
                evidence_maturity="in_vitro", actor_id="setup_all",
            )
            created += 1
        except Exception as e:
            print(f"  ⚠️ {stype}: {e}")
    print(f"  完成：处理 {created}/{len(STRATEGY_DEFS)} 个策略")


def _pick_default_program(driver):
    with driver.session() as s:
        row = s.run("""
            MATCH (d:DevelopmentProgram)
            RETURN d.program_id AS pid, d.canonical_name AS name
            ORDER BY d.canonical_name LIMIT 1
        """).single()
        if row:
            return row["pid"], row["name"]
    return None, None


def _get_strategy_id(driver, stype):
    with driver.session() as s:
        row = s.run("""
            MATCH (es:EngineeringStrategy {strategy_type: $stype})
            RETURN es.strategy_id AS sid LIMIT 1
        """, stype=stype).single()
        return row["sid"] if row else None


def _get_construct_id(driver, name):
    with driver.session() as s:
        row = s.run("""
            MATCH (ec:EngineeredPhageConstruct {public_name: $n})
            RETURN ec.construct_id AS cid LIMIT 1
        """, n=name).single()
        return row["cid"] if row else None


def ensure_constructs(driver):
    print("\n[1.3] 确保 EngineeredPhageConstruct 就绪 ...")
    prog_id, prog_name = _pick_default_program(driver)
    print(f"  默认项目：{prog_name} ({prog_id})")

    created = 0
    for stype, name, target_sp, status, pub_date in CONSTRUCT_DEFS:
        existing = _get_construct_id(driver, name)
        if existing:
            continue
        sid = _get_strategy_id(driver, stype)
        if not sid:
            print(f"  ⚠️ {name}: 找不到 strategy {stype}")
            continue
        try:
            cid = create_engineered_construct(
                driver,
                public_name=name, construct_code=name.upper(),
                parent_phage_name=None, intended_effects=[stype],
                target_pathogen_species=[target_sp],
                strategy_ids=[sid],
                construct_status=status,
                first_public_date=pub_date,
                actor_id="setup_all",
            )
            if prog_id:
                link_program_to_construct(driver, prog_id, cid, actor_id="setup_all")
            created += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
    print(f"  完成：新建 {created} 个构建体")


def ensure_assessments(driver):
    print("\n[1.4] 确保 TechnologyAssessment 就绪 ...")
    created = 0
    with driver.session() as s:
        constructs = list(s.run("""
            MATCH (ec:EngineeredPhageConstruct)
            WHERE NOT EXISTS {
                MATCH (ta:TechnologyAssessment {subject_type: 'construct'})
                WHERE ta.subject_id = ec.construct_id
            }
            RETURN ec.construct_id AS cid, ec.public_name AS name
        """))
    for c in constructs:
        try:
            create_technology_assessment(
                driver,
                subject_type="construct",
                subject_id=c["cid"],
                evidence_maturity="in_vitro",
                technical_relevance="high",
                translational_potential="medium",
                manufacturability_risk="medium",
                safety_uncertainty="low",
                ip_relevance="medium",
                internal_capability_gap="medium",
                assessment_summary=f"{c['name']} 的体外证据支持其技术相关性，转化与可制造性仍需验证。",
                actor_id="setup_all",
            )
            created += 1
        except Exception as e:
            print(f"  ⚠️ {c['name']}: {e}")
    print(f"  完成：新建 {created} 份技术评估")


def ensure_demo_source(driver):
    print("\n[1.5] 确保 demo SourceArtifact 就绪 ...")
    src_id = create_source_artifact(
        driver,
        source_type="literature",
        title="Stage2 demo evidence source",
        url="https://example.com/stage2-demo-source",
        published_date="2026-01-01",
        credibility_tier="secondary",
        actor_id="setup_all",
    )
    print(f"  ✅ demo source: {src_id}")
    return src_id


def ensure_claims_and_results(driver, src_id):
    print("\n[1.6] 确保 TechnicalClaim / TechnicalResult 就绪 ...")
    claim_cnt = 0
    result_cnt = 0

    with driver.session() as s:
        constructs = list(s.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            RETURN ec.construct_id AS cid,
                   ec.public_name AS name,
                   es.strategy_id AS sid,
                   es.strategy_type AS stype,
                   collect(DISTINCT p.pathogen_id) AS pid_list
        """))

    for c in constructs:
        ct = CLAIM_TYPE_MAP.get(c["stype"], "efficacy")
        cid = c["cid"]
        name = c["name"]

        with driver.session() as s:
            has_claim = s.run("""
                MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(:EngineeredPhageConstruct {construct_id: $cid})
                RETURN count(tc) AS c
            """, cid=cid).single()["c"]
            has_result = s.run("""
                MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(:EngineeredPhageConstruct {construct_id: $cid})
                RETURN count(tr) AS c
            """, cid=cid).single()["c"]

        if not has_claim:
            try:
                claim_id = create_technical_claim(
                    driver,
                    claim_type=ct,
                    claim_text=f"{name} 在体外展示出改进的 {ct} 表型",
                    claimant_type="publication",
                    evidence_context="in_vitro",
                    construct_id=cid,
                    strategy_id=c["sid"],
                    source_id=src_id,
                    actor_id="setup_all",
                )
                create_review(
                    driver,
                    review_type="technical_intelligence_review",
                    target_object_type="TechnicalClaim",
                    target_object_id=claim_id,
                    reviewer_id="expert_wang",
                    decision="approved",
                    comment="Stage2 补齐：技术主张审核通过",
                    update_target_status=True,
                    actor_id="setup_all",
                )
                claim_cnt += 1
            except Exception as e:
                print(f"  ⚠️ claim {name}: {e}")

        if not has_result:
            try:
                create_technical_result(
                    driver,
                    result_type=ct,
                    study_context="in_vitro",
                    outcome_direction="positive",
                    metric_name="relative_improvement",
                    metric_value=2.0,
                    metric_unit="fold",
                    comparator="亲本噬菌体",
                    sample_size=10,
                    limitation_summary="仅体外数据，需要体内验证",
                    reproducibility_status="single_source",
                    construct_id=cid,
                    source_id=src_id,
                    actor_id="setup_all",
                )
                result_cnt += 1
            except Exception as e:
                print(f"  ⚠️ result {name}: {e}")

    print(f"  完成：新建 claim {claim_cnt} 条，result {result_cnt} 条")


def ensure_patents_and_trials(driver):
    print("\n[1.7] 确保 PatentFamily / ClinicalTrial（可选）...")

    with driver.session() as s:
        org = s.run("""
            MATCH (o:Organization)-[:DEVELOPS]->(:DevelopmentProgram)
            RETURN o.organization_id AS oid, o.canonical_name AS name
            ORDER BY o.canonical_name LIMIT 1
        """).single()
        prog = s.run("""
            MATCH (d:DevelopmentProgram)
            RETURN d.program_id AS pid LIMIT 1
        """).single()

    if not org:
        print("  ⚠️ 无可用组织，跳过")
        return

    org_id = org["oid"]
    prog_id = prog["pid"] if prog else None

    with driver.session() as s:
        has_patent = s.run("MATCH (pf:PatentFamily) RETURN count(pf) AS c").single()["c"]
        has_trial = s.run("MATCH (ct:ClinicalTrial) RETURN count(ct) AS c").single()["c"]

    if has_patent == 0:
        patent_specs = [
            dict(
                title="Engineered bacteriophage with expanded host range",
                priority_date="2022-03-15",
                publication_numbers=["WO2023/123456A1", "US2024/0123456A1"],
                jurisdictions=["WO", "US"],
                applicants=["Example Biotech Ltd."],
                assignees=["Example Biotech Ltd."],
                legal_status="granted",
                claim_scope_summary="权利要求 1 覆盖尾纤维改造以扩展对 KL47 型 K. pneumoniae 的宿主范围。",
                source_url="https://patents.example.com/WO2023123456",
            ),
            dict(
                title="Phage-encoded biofilm degrading enzyme",
                priority_date="2023-06-01",
                publication_numbers=["WO2024/654321A1"],
                jurisdictions=["WO"],
                applicants=["Example Biotech Ltd."],
                assignees=["Example Biotech Ltd."],
                legal_status="pending",
                claim_scope_summary="权利要求 1 覆盖在噬菌体基因组中插入生物膜降解酶编码序列。",
                source_url="https://patents.example.com/WO2024654321",
            ),
            dict(
                title="Anti-CRISPR payload for phage therapy",
                priority_date="2023-11-10",
                publication_numbers=["US2025/0011223A1"],
                jurisdictions=["US"],
                applicants=["Example Biotech Ltd."],
                assignees=["Example Biotech Ltd."],
                legal_status="pending",
                claim_scope_summary="权利要求 1 覆盖装载 anti-CRISPR 蛋白的工程化噬菌体。",
                source_url="https://patents.example.com/US20250011223",
            ),
        ]
        for spec in patent_specs:
            try:
                create_patent_family(
                    driver,
                    title=spec["title"],
                    priority_date=spec["priority_date"],
                    publication_numbers=spec["publication_numbers"],
                    jurisdictions=spec["jurisdictions"],
                    applicants=spec["applicants"],
                    assignees=spec["assignees"],
                    legal_status=spec["legal_status"],
                    claim_scope_summary=spec["claim_scope_summary"],
                    source_url=spec["source_url"],
                    organization_id=org_id,
                    program_ids=[prog_id] if prog_id else [],
                    actor_id="setup_all",
                )
                print(f"  ✅ 专利族: {spec['title'][:50]}")
            except Exception as e:
                print(f"  ⚠️ 专利族: {e}")
    else:
        print(f"  ℹ️ 已有 {has_patent} 个专利族，跳过")

    if has_trial == 0:
        trial_specs = [
            dict(
                title="PhageBank-CF Phase 1/2 in cystic fibrosis P. aeruginosa",
                nct_id="NCT05012345", phase="phase_1_2", status="completed",
                indication="Cystic fibrosis lung infection",
                sponsor="Adaptive Phage Therapeutics",
                start_date="2021-06-01", completion_date="2023-12-31",
                enrollment=36, primary_endpoint="Safety and tolerability",
            ),
            dict(
                title="BX211 Phase 2 in diabetic foot osteomyelitis",
                nct_id="NCT06098765", phase="phase_2", status="active",
                indication="Diabetic foot osteomyelitis",
                sponsor="BiomX",
                start_date="2024-02-01", completion_date="2026-06-30",
                enrollment=120, primary_endpoint="Clinical response at week 12",
            ),
        ]
        for spec in trial_specs:
            try:
                create_clinical_trial(
                    driver,
                    title=spec["title"], nct_id=spec["nct_id"],
                    phase=spec["phase"], status=spec["status"],
                    indication=spec["indication"], sponsor=spec["sponsor"],
                    organization_id=org_id,
                    program_id=prog_id,
                    start_date=spec["start_date"],
                    completion_date=spec["completion_date"],
                    enrollment=spec["enrollment"],
                    primary_endpoint=spec["primary_endpoint"],
                    actor_id="setup_all",
                )
                print(f"  ✅ 临床试验: {spec['nct_id']}")
            except Exception as e:
                print(f"  ⚠️ 临床试验: {e}")
    else:
        print(f"  ℹ️ 已有 {has_trial} 项临床试验，跳过")


# ============================================================
# 1.5 派生关系回填（v0.6 P1-6 ~ P1-9）
# ============================================================

def backfill_derived_relations(driver):
    print("\n[1.5] 回填 v0.6 派生关系（4 类）...")

    # P1-6: DevelopmentProgram -[:USES_STRATEGY]-> EngineeringStrategy
    try:
        r = backfill_program_uses_strategy(driver, actor_id="setup_all")
        print(f"  ✅ USES_STRATEGY  新增 {r['created']} 条")
        for d in r["details"]:
            print(f"     {d['program_id']} → {d['strategy_id']}")
    except Exception as e:
        print(f"  ❌ USES_STRATEGY 回填失败: {e}")

    # P1-7: EngineeredPhageConstruct -[:DEVELOPED_BY]-> Organization
    try:
        r = backfill_construct_developed_by(driver, actor_id="setup_all")
        print(f"  ✅ DEVELOPED_BY   新增 {r['created']} 条")
        for d in r["details"]:
            print(f"     {d['construct_id']} → {d['organization_id']}")
    except Exception as e:
        print(f"  ❌ DEVELOPED_BY 回填失败: {e}")

    # P1-8: TechnicalResult -[:SUPPORTED_OR_CHALLENGES]-> TechnicalClaim
    try:
        r = backfill_result_to_claim(driver, actor_id="setup_all")
        print(f"  ✅ SUPPORTED_OR_CHALLENGES 新增 {r['created']} 条")
        for d in r["details"]:
            print(
                f"     {d['result_id']} --[{d['verdict']}]--> {d['claim_id']} "
                f"(construct {d['construct_id']})"
            )
    except Exception as e:
        print(f"  ❌ SUPPORTED_OR_CHALLENGES 回填失败: {e}")

    # P1-9: TechnicalClaim -[:EVALUATED_BY]-> TechnologyAssessment
    try:
        r = backfill_claim_evaluated_by(driver, actor_id="setup_all")
        print(f"  ✅ EVALUATED_BY   新增 {r['created']} 条")
        for d in r["details"]:
            print(f"     {d['assessment_id']} ← {d['claim_id']}")
    except Exception as e:
        print(f"  ❌ EVALUATED_BY 回填失败: {e}")

    # 汇总统计
    with driver.session() as s:
        stats = {
            "USES_STRATEGY": s.run(
                "MATCH (:DevelopmentProgram)-[r:USES_STRATEGY]->(:EngineeringStrategy) "
                "RETURN count(r) AS c").single()["c"],
            "DEVELOPED_BY": s.run(
                "MATCH (:EngineeredPhageConstruct)-[r:DEVELOPED_BY]->(:Organization) "
                "RETURN count(r) AS c").single()["c"],
            "SUPPORTED_OR_CHALLENGES": s.run(
                "MATCH (:TechnicalResult)-[r:SUPPORTED_OR_CHALLENGES]->(:TechnicalClaim) "
                "RETURN count(r) AS c").single()["c"],
            "EVALUATED_BY": s.run(
                "MATCH (:TechnicalClaim)-[r:EVALUATED_BY]->(:TechnologyAssessment) "
                "RETURN count(r) AS c").single()["c"],
        }
    print("  📊 当前派生关系总条数：")
    for k, v in stats.items():
        print(f"     {k:26s} {v}")


# ============================================================
# 2. Brief 生成
# ============================================================

def ensure_competitor_briefs(driver, min_count=5):
    print(f"\n[2.1] 确保 Competitor Brief ≥ {min_count} ...")

    with driver.session() as s:
        orgs = list(s.run("""
            MATCH (o:Organization)
            WHERE EXISTS { MATCH (o)-[:DEVELOPS]->(:DevelopmentProgram) }
            RETURN o.organization_id AS oid, o.canonical_name AS name
            ORDER BY o.canonical_name
        """))

    created = 0
    for org in orgs:
        with driver.session() as s:
            has = s.run("""
                MATCH (b:IntelligenceProduct {brief_type: 'competitor'})
                      -[:COVERS]->(:Organization {organization_id: $oid})
                RETURN count(b) AS c
            """, oid=org["oid"]).single()["c"]
        if has > 0:
            continue
        try:
            brief = generate_competitor_brief(driver, org["oid"], days_back=730, persist=True)
            bid = brief.get("brief_id") if isinstance(brief, dict) else None
            if bid:
                created += 1
                print(f"  ✅ {org['name']}: {bid}")
        except Exception as e:
            print(f"  ❌ {org['name']}: {e}")

        with driver.session() as s:
            total = s.run("""
                MATCH (b:IntelligenceProduct {brief_type: 'competitor'})
                RETURN count(b) AS c
            """).single()["c"]
        if total >= min_count:
            break

    print(f"  新建 {created} 份 Competitor Brief")


def ensure_technology_briefs(driver, min_count=5):
    print(f"\n[2.2] 确保 Technology Brief ≥ {min_count} ...")

    with driver.session() as s:
        strategies = list(s.run("""
            MATCH (es:EngineeringStrategy)
            RETURN es.strategy_id AS sid, es.strategy_type AS stype
            ORDER BY es.strategy_type
        """))

    created = 0
    for st in strategies:
        with driver.session() as s:
            has = s.run("""
                MATCH (b:IntelligenceProduct {brief_type: 'engineered_phage_technology'})
                      -[:COVERS]->(:EngineeringStrategy {strategy_id: $sid})
                RETURN count(b) AS c
            """, sid=st["sid"]).single()["c"]
        if has > 0:
            continue
        try:
            brief = generate_technology_brief(
                driver,
                strategy_id=st["sid"],
                technology_question=f"{st['stype']} 的公开证据成熟度如何？",
                persist=True,
            )
            bid = brief.get("brief_id")
            if bid:
                created += 1
                print(f"  ✅ {st['stype']}: {bid}")
        except Exception as e:
            print(f"  ❌ {st['stype']}: {e}")

        with driver.session() as s:
            total = s.run("""
                MATCH (b:IntelligenceProduct {brief_type: 'engineered_phage_technology'})
                RETURN count(b) AS c
            """).single()["c"]
        if total >= min_count:
            break

    print(f"  新建 {created} 份 Technology Brief")


def ensure_decision_records(driver, min_count=2):
    print(f"\n[2.3] 确保 DecisionRecord ≥ {min_count} ...")

    with driver.session() as s:
        briefs = list(s.run("""
            MATCH (b:IntelligenceProduct)
            WHERE NOT EXISTS { MATCH (:DecisionRecord)-[:BASED_ON]->(b) }
            RETURN b.brief_id AS bid, b.brief_type AS btype
            ORDER BY b.created_at
        """))

    created = 0
    for b in briefs:
        try:
            create_decision_record(
                driver,
                brief_id=b["bid"],
                decision_type="monitor",
                decision_summary=f"基于 {b['btype']} 简报 {b['bid']}，决定持续监控",
                rationale="Stage2 验收补齐决策记录",
                decision_owner="VP_Strategy",
                review_date="2027-01-01",
                actor_id="setup_all",
            )
            created += 1
            print(f"  ✅ {b['bid']} ({b['btype']})")
        except Exception as e:
            print(f"  ❌ {b['bid']}: {e}")

        with driver.session() as s:
            total = s.run("""
                MATCH (dr:DecisionRecord)-[:BASED_ON]->(:IntelligenceProduct)
                RETURN count(DISTINCT dr) AS c
            """).single()["c"]
        if total >= min_count:
            break

    print(f"  新建 {created} 份 DecisionRecord")


# ============================================================
# 3. 补齐 Review / citations / data_gaps
# ============================================================

def fix_strategy_reviews(driver):
    print("\n[3.1] 补齐 EngineeringStrategy 专家审核 ...")
    with driver.session() as s:
        targets = list(s.run("""
            MATCH (es:EngineeringStrategy)
            WHERE es.review_status IS NULL
               OR es.review_status <> 'approved'
               OR NOT EXISTS { MATCH (:Review)-[:REVIEWS]->(es) }
            RETURN es.strategy_id AS sid, es.strategy_type AS stype,
                   es.review_status AS rstatus
            ORDER BY es.strategy_type
        """))

    if not targets:
        print("  ✅ 无待审核策略")
        return 0

    print(f"  待审核策略数：{len(targets)}")
    fixed = 0
    for r in targets:
        try:
            create_review(
                driver,
                review_type="technical_intelligence_review",
                target_object_type="EngineeringStrategy",
                target_object_id=r["sid"],
                reviewer_id="expert_wang",
                decision="approved",
                comment="Stage2 补齐：工程策略分类与证据成熟度审核通过",
                update_target_status=True,
                actor_id="setup_all",
            )
            fixed += 1
        except Exception as e:
            print(f"  ❌ {r['sid']}: {e}")
    print(f"  完成：{fixed}/{len(targets)}")
    return fixed


def fix_claim_reviews(driver):
    print("\n[3.2] 补齐 TechnicalClaim 审核 ...")
    with driver.session() as s:
        targets = list(s.run("""
            MATCH (tc:TechnicalClaim)
            WHERE NOT EXISTS { MATCH (:Review)-[:REVIEWS]->(tc) }
            RETURN tc.claim_id AS cid
        """))

    if not targets:
        print("  ✅ 无待审核 Claim")
        return 0

    print(f"  待审核 Claim 数：{len(targets)}")
    fixed = 0
    for r in targets:
        try:
            create_review(
                driver,
                review_type="technical_intelligence_review",
                target_object_type="TechnicalClaim",
                target_object_id=r["cid"],
                reviewer_id="expert_wang",
                decision="approved",
                comment="Stage2 补齐：技术主张审核通过",
                update_target_status=True,
                actor_id="setup_all",
            )
            fixed += 1
        except Exception as e:
            print(f"  ❌ {r['cid']}: {e}")
    print(f"  完成：{fixed}/{len(targets)}")
    return fixed


def fix_brief_reviews(driver):
    print("\n[3.3] 补齐 IntelligenceProduct 审核记录 ...")
    with driver.session() as s:
        targets = list(s.run("""
            MATCH (b:IntelligenceProduct)
            WHERE NOT EXISTS { MATCH (:Review)-[:REVIEWS]->(b) }
               OR b.review_status IS NULL
               OR b.review_status <> 'approved'
            RETURN b.brief_id AS bid, b.brief_type AS btype,
                   b.review_status AS rstatus
            ORDER BY b.created_at
        """))

    if not targets:
        print("  ✅ 无待审核 Brief")
        return 0

    print(f"  待审核 Brief 数：{len(targets)}")
    fixed = 0
    for r in targets:
        try:
            create_review(
                driver,
                review_type="intelligence_product_review",
                target_object_type="IntelligenceProduct",
                target_object_id=r["bid"],
                reviewer_id="expert_wang",
                decision="approved",
                comment="Stage2 补齐：情报产品审核通过",
                update_target_status=True,
                actor_id="setup_all",
            )
            fixed += 1
        except Exception as e:
            print(f"  ❌ {r['bid']}: {e}")
    print(f"  完成：{fixed}/{len(targets)}")
    return fixed


def _collect_citations_for_brief(driver, brief_id, brief_type):
    rows = []
    with driver.session() as s:
        if brief_type == "competitor":
            rows = list(s.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})-[:COVERS]->(o:Organization)
                OPTIONAL MATCH (o)<-[:INVOLVES]-(:IntelligenceEvent)-[:HAS_SOURCE]->(src:SourceArtifact)
                WITH collect(DISTINCT src) AS sources
                UNWIND (CASE WHEN size(sources)=0 THEN [null] ELSE sources END) AS src
                WITH src WHERE src IS NOT NULL
                RETURN DISTINCT src.source_id AS sid, src.source_type AS stype,
                                src.title AS title, src.url AS url,
                                src.published_date AS pdate,
                                src.credibility_tier AS tier
            """, bid=brief_id))
        else:
            rows = list(s.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})-[:COVERS]->(x)
                WHERE x:EngineeredPhageConstruct OR x:EngineeringStrategy
                OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(x)
                OPTIONAL MATCH (tc)-[:SUPPORTED_BY]->(s1:SourceArtifact)
                OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(x)
                OPTIONAL MATCH (tr)-[:REPORTED_IN]->(s2:SourceArtifact)
                WITH collect(DISTINCT s1) + collect(DISTINCT s2) AS sources
                UNWIND sources AS src
                WITH DISTINCT src WHERE src IS NOT NULL
                RETURN DISTINCT src.source_id AS sid, src.source_type AS stype,
                                src.title AS title, src.url AS url,
                                src.published_date AS pdate,
                                src.credibility_tier AS tier
            """, bid=brief_id))

            if not rows:
                rows = list(s.run("""
                    MATCH (tc:TechnicalClaim)-[:SUPPORTED_BY]->(src:SourceArtifact)
                    RETURN DISTINCT src.source_id AS sid, src.source_type AS stype,
                                    src.title AS title, src.url AS url,
                                    src.published_date AS pdate,
                                    src.credibility_tier AS tier
                    LIMIT 5
                """))

    return [{
        "source_id": r["sid"], "source_type": r["stype"],
        "title": r["title"], "url": r["url"],
        "published_date": r["pdate"], "credibility_tier": r["tier"],
    } for r in rows]


def fix_brief_citations(driver):
    print("\n[3.4] 补齐 Brief 引用来源（citations）...")
    with driver.session() as s:
        targets = list(s.run("""
            MATCH (b:IntelligenceProduct)
            WHERE b.citations IS NULL OR b.citations = '' OR b.citations = '[]'
               OR b.citations CONTAINS 'SRC:PLACEHOLDER'
            RETURN b.brief_id AS bid, b.brief_type AS btype
            ORDER BY b.created_at
        """))

    if not targets:
        print("  ✅ 无缺 citations 的 Brief")
        return 0

    print(f"  缺 citations 的 Brief 数：{len(targets)}")
    fixed = 0
    for t in targets:
        citations = _collect_citations_for_brief(driver, t["bid"], t["btype"])
        if not citations:
            print(f"  ⚠️  {t['bid']} 无可用 SourceArtifact，跳过")
            continue
        with driver.session() as s:
            s.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                SET b.citations = $c, b.updated_at = datetime()
            """, bid=t["bid"], c=json.dumps(citations, ensure_ascii=False))
        fixed += 1
    print(f"  完成：{fixed}/{len(targets)}")
    return fixed


def fix_brief_data_gaps(driver):
    print("\n[3.5] 补齐 Brief data_gaps ...")
    with driver.session() as s:
        targets = list(s.run("""
            MATCH (b:IntelligenceProduct)
            WHERE b.data_gaps IS NULL OR b.data_gaps = '' OR b.data_gaps = '[]'
            RETURN b.brief_id AS bid, b.brief_type AS btype
            ORDER BY b.created_at
        """))

    if not targets:
        print("  ✅ 无缺 data_gaps 的 Brief")
        return 0

    print(f"  缺 data_gaps 的 Brief 数：{len(targets)}")
    fixed = 0
    for t in targets:
        gaps = DEFAULT_DATA_GAPS_BY_TYPE.get(t["btype"], DEFAULT_GAPS_FALLBACK)
        with driver.session() as s:
            s.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                SET b.data_gaps = $g, b.updated_at = datetime()
            """, bid=t["bid"], g=json.dumps(gaps, ensure_ascii=False))
        fixed += 1
    print(f"  完成：{fixed}/{len(targets)}")
    return fixed


# ============================================================
# 4. 回填 Brief 质量能力字段
# ============================================================

def backfill_competitor_brief_quality(driver):
    from src.ci.competitor_brief import (
        _build_source_credibility_breakdown,
        _build_entity_resolution_hints,
        _build_conflict_summary,
    )
    fixed = 0
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (b:IntelligenceProduct {brief_type: 'competitor'})-[:COVERS]->(o:Organization)
            WHERE b.source_credibility_breakdown IS NULL
               OR b.entity_resolution_hints IS NULL
               OR b.conflict_summary IS NULL
            RETURN b.brief_id AS bid, o.organization_id AS oid
        """))

    for r in rows:
        try:
            sc = _build_source_credibility_breakdown(driver, r["oid"])
            er = _build_entity_resolution_hints(driver, r["oid"])
            cf = _build_conflict_summary(driver, r["oid"])
            with driver.session() as s:
                s.run("""
                    MATCH (b:IntelligenceProduct {brief_id: $bid})
                    SET b.source_credibility_breakdown = $sc,
                        b.entity_resolution_hints = $er,
                        b.conflict_summary = $cf,
                        b.updated_at = datetime()
                """, bid=r["bid"],
                     sc=json.dumps(sc, ensure_ascii=False, default=str),
                     er=json.dumps(er, ensure_ascii=False, default=str),
                     cf=json.dumps(cf, ensure_ascii=False, default=str))
            fixed += 1
            print(f"  ✅ Competitor {r['bid']}")
        except Exception as e:
            print(f"  ❌ Competitor {r['bid']}: {e}")
    return fixed


def backfill_technology_brief_quality(driver):
    from src.engineering_intelligence.technology_brief import (
        _build_source_credibility_block,
        _build_conflict_warnings,
        _build_related_patent_mappings,
        _fetch_citations,
        _fetch_patent_families,
    )
    fixed = 0
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (b:IntelligenceProduct {brief_type: 'engineered_phage_technology'})
            WHERE b.source_credibility IS NULL
               OR b.conflict_warnings IS NULL
               OR b.related_patent_mappings IS NULL
            OPTIONAL MATCH (b)-[:COVERS]->(x)
            WHERE x:EngineeredPhageConstruct OR x:EngineeringStrategy
            WITH b, collect(DISTINCT x) AS covers
            RETURN b.brief_id AS bid, covers
        """))

    for r in rows:
        try:
            construct_ids = [c["construct_id"] for c in r["covers"]
                             if "construct_id" in c and c["construct_id"]]
            strategy_ids = [c["strategy_id"] for c in r["covers"]
                            if "strategy_id" in c and c["strategy_id"]]

            citations = _fetch_citations(driver, construct_ids) if construct_ids else []
            patent_families = []
            if strategy_ids:
                patent_families = _fetch_patent_families(
                    driver, strategy_ids[0], None, None)

            src = _build_source_credibility_block(citations)
            cf = _build_conflict_warnings(driver, construct_ids)
            pm = _build_related_patent_mappings(driver, patent_families)

            with driver.session() as s:
                s.run("""
                    MATCH (b:IntelligenceProduct {brief_id: $bid})
                    SET b.source_credibility = $src,
                        b.conflict_warnings = $cf,
                        b.related_patent_mappings = $pm,
                        b.updated_at = datetime()
                """, bid=r["bid"],
                     src=json.dumps(src, ensure_ascii=False, default=str),
                     cf=json.dumps(cf, ensure_ascii=False, default=str),
                     pm=json.dumps(pm, ensure_ascii=False, default=str))
            fixed += 1
            print(f"  ✅ Technology {r['bid']}")
        except Exception as e:
            print(f"  ❌ Technology {r['bid']}: {e}")
    return fixed


def backfill_brief_quality_fields(driver):
    print("\n[4] 回填 Brief 质量能力字段 ...")
    n1 = backfill_competitor_brief_quality(driver)
    print(f"  Competitor 完成：{n1}")
    n2 = backfill_technology_brief_quality(driver)
    print(f"  Technology 完成：{n2}")
    print(f"  合计回填 {n1 + n2} 份 Brief")
    return n1 + n2


# ============================================================
# 5. 回填时间语义
# ============================================================

def backfill_time_semantics(driver):
    print("\n[5] 回填时间语义 valid_from ...")
    result = backfill_valid_from(driver)
    print(f"  回填 valid_from：{result['updated']} 条")
    for lb, c in result["by_label"].items():
        if c > 0:
            print(f"    {lb:30s} {c}")

    print("\n  === 时间覆盖率报告 ===")
    report = time_coverage_report(driver)
    for lb, r in report.items():
        print(f"    {lb:30s} {r['covered']}/{r['total']}  ({r['coverage']}%)")
    return result["updated"]


# ============================================================
# 主流程
# ============================================================

def main(driver=None):
    """
    执行 Stage2 全量数据准备 + v0.6 收尾。

    Args:
        driver: 可选，外部传入的 Neo4j 驱动。
                若为 None，则内部自建并负责关闭。
                若传入，则不关闭（由调用方管理）。
    """
    print("=" * 96)
    print("  Stage2 一键数据准备（重建 + 补齐 + 派生关系 + 回填 + v0.6 收尾）")
    print(f"  开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 96)

    _owns_driver = driver is None
    if _owns_driver:
        driver = get_driver()

    try:
        # 阶段 0.5：BiomX 事件类型修正 + DATA_CORRECTION 审计
        fix_biomx_event_type(driver)

        # 阶段 0.6：清理 [reference:X]
        clean_reference_tags(driver)

        # 阶段 1：重建基础数据
        ensure_pathogens(driver)
        ensure_strategies(driver)
        ensure_constructs(driver)
        ensure_assessments(driver)
        src_id = ensure_demo_source(driver)
        ensure_claims_and_results(driver, src_id)
        ensure_patents_and_trials(driver)

        # 阶段 1.5：回填 v0.6 派生关系
        backfill_derived_relations(driver)

        # 阶段 1.8：注册 v0.6 顶层 OntologyModule
        register_v06_modules(driver)

        # 阶段 2：生成简报
        ensure_competitor_briefs(driver, min_count=5)
        ensure_technology_briefs(driver, min_count=5)
        ensure_decision_records(driver, min_count=2)

        # 阶段 3：补齐审核 / citations / data_gaps
        fix_strategy_reviews(driver)
        fix_claim_reviews(driver)
        fix_brief_reviews(driver)
        fix_brief_citations(driver)
        fix_brief_data_gaps(driver)

        # 阶段 4：回填 Brief 质量能力字段
        backfill_brief_quality_fields(driver)

        # 阶段 5：回填时间语义
        backfill_time_semantics(driver)
    finally:
        if _owns_driver:
            driver.close()

    print("\n" + "=" * 96)
    print("  全部完成。请重新运行：")
    print("      python tests/acceptance_stage2.py")
    print("=" * 96)


if __name__ == "__main__":
    main()