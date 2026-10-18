# data_access/queries.py
"""
Dash 前端只读数据访问层。
- 所有 Cypher 集中于此
- 字段名、关系名与 src/ 严格一致
- 页面里禁止写裸 Cypher
"""
from typing import List, Dict
from config import get_driver


def _run(cypher: str, **params) -> List[Dict]:
    with get_driver().session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


# ============================================================
# Scientific Domain
# ============================================================

def list_phages(keyword="", family="", limit=500) -> List[Dict]:
    return _run("""
        MATCH (p:Phage)
        WHERE ($kw = '' OR toLower(p.name) CONTAINS toLower($kw))
          AND ($fam = '' OR p.family = $fam)
        RETURN p.phage_id AS id, p.name AS name,
               p.family AS family, p.receptor_target AS receptor_target
        ORDER BY p.name LIMIT $limit
    """, kw=keyword, fam=family, limit=limit)


def list_host_strains(keyword="", species="", limit=500) -> List[Dict]:
    return _run("""
        MATCH (h:HostStrain)
        WHERE ($kw = '' OR toLower(h.strain_label) CONTAINS toLower($kw))
          AND ($sp = '' OR EXISTS {
              MATCH (h)-[:IS_STRAIN_OF]->(p:Pathogen) WHERE p.species = $sp
          })
        OPTIONAL MATCH (h)-[:IS_STRAIN_OF]->(p:Pathogen)
        RETURN h.host_strain_id AS id, h.strain_label AS label,
               p.species AS species
        ORDER BY h.strain_label LIMIT $limit
    """, kw=keyword, sp=species, limit=limit)


def list_lysis_assays(keyword="", result="", limit=500) -> List[Dict]:
    return _run("""
        MATCH (a:LysisAssay)
        WHERE ($kw = '' OR toLower(a.assay_id) CONTAINS toLower($kw))
          AND ($rs = '' OR a.result = $rs)
        OPTIONAL MATCH (ph:Phage)-[:USED_IN]->(a)
        OPTIONAL MATCH (a)-[:TESTED_AGAINST]->(h:HostStrain)
        RETURN a.assay_id AS id, a.result AS result,
               a.result_value AS result_value,
               a.evidence_level AS evidence_level,
               a.qc_status AS qc_status,
               ph.phage_id AS phage_id, ph.name AS phage_name,
               h.strain_label AS host_label
        ORDER BY a.evidence_level DESC LIMIT $limit
    """, kw=keyword, rs=result, limit=limit)


def list_clinical_cases(keyword="", outcome="", limit=200) -> List[Dict]:
    return _run("""
        MATCH (c:ClinicalCase)
        WHERE ($kw = '' OR toLower(c.case_id) CONTAINS toLower($kw))
          AND ($oc = '' OR c.clinical_outcome = $oc)
        OPTIONAL MATCH (c)-[:INVOLVES_PATHOGEN]->(p:Pathogen)
        OPTIONAL MATCH (c)-[:HAS_ISOLATE]->(h:HostStrain)
        RETURN c.case_id AS id,
               c.infection_type AS infection_type,
               c.clinical_outcome AS clinical_outcome,
               c.phage_treatment AS phage_treatment,
               p.species AS pathogen_species,
               h.strain_label AS host_strain
        ORDER BY c.case_id DESC LIMIT $limit
    """, kw=keyword, oc=outcome, limit=limit)


def list_evidence_packages(keyword="", status="", limit=200) -> List[Dict]:
    return _run("""
        MATCH (pkg:ScientificEvidencePackage)
        WHERE ($kw = '' OR toLower(pkg.package_id) CONTAINS toLower($kw))
          AND ($st = '' OR pkg.status = $st)
        RETURN pkg.package_id AS id, pkg.package_type AS package_type,
               pkg.status AS status, pkg.review_status AS review_status,
               pkg.generated_by AS generated_by,
               pkg.created_at AS created_at
        ORDER BY pkg.created_at DESC LIMIT $limit
    """, kw=keyword, st=status, limit=limit)


# ============================================================
# CI Domain
# ============================================================

def list_organizations(keyword="", org_type="", limit=500) -> List[Dict]:
    return _run("""
        MATCH (o:Organization)
        WHERE ($kw = '' OR toLower(o.canonical_name) CONTAINS toLower($kw))
          AND ($tp = '' OR o.organization_type = $tp)
        RETURN o.organization_id AS id, o.canonical_name AS name,
               o.organization_type AS organization_type,
               o.headquarters_country AS country,
               o.website AS website
        ORDER BY o.canonical_name LIMIT $limit
    """, kw=keyword, tp=org_type, limit=limit)


def list_programs(keyword="", stage="", status="", limit=200) -> List[Dict]:
    return _run("""
        MATCH (p:DevelopmentProgram)
        WHERE ($kw = '' OR toLower(p.canonical_name) CONTAINS toLower($kw))
          AND ($st = '' OR p.development_stage = $st)
          AND ($ss = '' OR p.program_status = $ss)
        OPTIONAL MATCH (o:Organization)-[:DEVELOPS]->(p)
        OPTIONAL MATCH (p)-[:TARGETS_PATHOGEN]->(path:Pathogen)
        RETURN p.program_id AS id, p.canonical_name AS name,
               p.development_stage AS stage,
               p.program_status AS status,
               p.modality AS modality,
               o.canonical_name AS org_name,
               collect(DISTINCT path.species) AS pathogens
        ORDER BY p.canonical_name LIMIT $limit
    """, kw=keyword, st=stage, ss=status, limit=limit)


def list_intelligence_events(keyword="", event_type="", limit=200) -> List[Dict]:
    return _run("""
        MATCH (e:IntelligenceEvent)
        WHERE ($kw = '' OR toLower(e.title) CONTAINS toLower($kw))
          AND ($et = '' OR e.event_type = $et)
        OPTIONAL MATCH (e)-[:INVOLVES]->(o:Organization)
        OPTIONAL MATCH (e)-[:HAS_SOURCE]->(s:SourceArtifact)
        RETURN e.event_id AS id, e.title AS title,
               e.event_type AS event_type, e.event_date AS event_date,
               e.organization_id AS organization_id,
               o.canonical_name AS org_name,
               s.source_id AS source_id
        ORDER BY e.event_date DESC LIMIT $limit
    """, kw=keyword, et=event_type, limit=limit)


def list_decision_records(keyword="", decision_type="", limit=200) -> List[Dict]:
    return _run("""
        MATCH (d:DecisionRecord)
        WHERE ($kw = '' OR toLower(d.decision_summary) CONTAINS toLower($kw))
          AND ($dt = '' OR d.decision_type = $dt)
        OPTIONAL MATCH (d)-[:BASED_ON]->(b:IntelligenceProduct)
        RETURN d.decision_id AS id, d.decision_type AS decision_type,
               d.decision_summary AS summary,
               d.decision_owner AS owner,
               d.outcome_status AS outcome_status,
               b.brief_id AS brief_id
        ORDER BY d.decided_at DESC LIMIT $limit
    """, kw=keyword, dt=decision_type, limit=limit)


def list_strategies(keyword="", strategy_type="", limit=100) -> List[Dict]:
    return _run("""
        MATCH (s:EngineeringStrategy)
        WHERE ($kw = '' OR toLower(s.strategy_type) CONTAINS toLower($kw))
          AND ($st = '' OR s.strategy_type = $st)
        OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(s)
        RETURN s.strategy_id AS id, s.strategy_type AS strategy_type,
               s.description AS description,
               s.evidence_maturity AS evidence_maturity,
               s.review_status AS review_status,
               count(DISTINCT ec) AS construct_count
        ORDER BY s.strategy_type LIMIT $limit
    """, kw=keyword, st=strategy_type, limit=limit)


def list_tech_assessments(keyword="", limit=100) -> List[Dict]:
    return _run("""
        MATCH (ta:TechnologyAssessment)
        WHERE ($kw = '' OR toLower(ta.subject_id) CONTAINS toLower($kw))
        RETURN ta.technology_assessment_id AS id,
               ta.subject_type AS subject_type,
               ta.subject_id AS subject_id,
               ta.evidence_maturity AS evidence_maturity,
               ta.technical_relevance AS technical_relevance,
               ta.translational_potential AS translational_potential,
               ta.assessment_summary AS summary
        ORDER BY ta.created_at DESC LIMIT $limit
    """, kw=keyword, limit=limit)


# ============================================================
# Admin
# ============================================================

def list_audit_events(action_type="", object_type="", limit=500,
                      offset=0) -> List[Dict]:
    return _run("""
        MATCH (a:AuditEvent)
        WHERE ($at = '' OR a.action_type = $at)
          AND ($ot = '' OR a.object_type = $ot)
        RETURN a.audit_id AS id, a.action_type AS action_type,
               a.object_type AS object_type, a.object_id AS object_id,
               a.actor_id AS actor_id, a.timestamp AS timestamp,
               a.reason AS reason
        ORDER BY a.timestamp DESC
        SKIP $offset LIMIT $limit
    """, at=action_type, ot=object_type, limit=limit, offset=offset)


def list_ontology_modules() -> List[Dict]:
    return _run("""
        MATCH (m:OntologyModule)
        RETURN m.module_id AS id, m.module_name AS module_name,
               m.version AS version, m.status AS status,
               m.owner_team AS owner_team
        ORDER BY m.module_name
    """)


# ============================================================
# Dashboard KPI
# ============================================================

def dashboard_stats() -> Dict:
    with get_driver().session() as s:
        def one(cypher):
            r = s.run(cypher).single()
            return r[0] if r else 0
        return {
            "phages":    one("MATCH (p:Phage) RETURN count(p)"),
            "cases":     one("MATCH (c:ClinicalCase) RETURN count(c)"),
            "assays":    one("MATCH (a:LysisAssay) RETURN count(a)"),
            "orgs":      one("MATCH (o:Organization) RETURN count(o)"),
            "programs":  one("MATCH (p:DevelopmentProgram) RETURN count(p)"),
            "events":    one("MATCH (e:IntelligenceEvent) RETURN count(e)"),
            "briefs":    one("MATCH (b:IntelligenceProduct) RETURN count(b)"),
            "decisions": one("MATCH (d:DecisionRecord) RETURN count(d)"),
            "audits":    one("MATCH (a:AuditEvent) RETURN count(a)"),
            "constructs": one("MATCH (ec:EngineeredPhageConstruct) RETURN count(ec)"),
        }


def list_intelligence_events_for_board(limit=200):
    """情报概览页用：含影响级别和归因组织"""
    return _run("""
        MATCH (e:IntelligenceEvent)
        OPTIONAL MATCH (e)-[:INVOLVES]->(o:Organization)
        RETURN e.event_id AS id, e.title AS title,
               e.event_type AS event_type,
               e.event_date AS event_date,
               e.materiality AS impact_level,
               o.canonical_name AS org_name
        ORDER BY e.event_date DESC
        LIMIT $limit
    """, limit=limit)


def list_programs_for_pipeline(limit=100):
    """情报概览页用：按阶段分组"""
    return _run("""
        MATCH (p:DevelopmentProgram)
        OPTIONAL MATCH (o:Organization)-[:DEVELOPS]->(p)
        RETURN p.program_id AS id, p.canonical_name AS name,
               p.development_stage AS stage,
               p.program_status AS status,
               o.canonical_name AS org_name
        LIMIT $limit
    """, limit=limit)


def intelligence_board_kpis():
    with get_driver().session() as s:
        def one(cypher):
            r = s.run(cypher).single()
            return r[0] if r else 0
        return {
            "total_events":  one("MATCH (e:IntelligenceEvent) RETURN count(e)"),
            "high_impact":   one("""
                MATCH (e:IntelligenceEvent)
                WHERE e.materiality IN ['high', 'critical']
                   OR e.event_type IN ['acquisition', 'merger']
                RETURN count(e)
            """),
            "active_programs": one("""
                MATCH (p:DevelopmentProgram)
                WHERE p.program_status = 'active'
                RETURN count(p)
            """),
            "orgs_involved": one("""
                MATCH (e:IntelligenceEvent)-[:INVOLVES]->(o:Organization)
                RETURN count(DISTINCT o)
            """),
        }


def list_constraints():
    """Schema 页：当前所有约束"""
    with get_driver().session() as s:
        rows = list(s.run("SHOW CONSTRAINTS"))
        out = []
        for r in rows:
            d = dict(r)
            out.append({
                "name": d.get("name"),
                "type": d.get("type"),
                "labelsOrTypes": d.get("labelsOrTypes") or [],
                "properties": d.get("properties") or [],
            })
        return out


# ============================================================
# ★ 新增：Dashboard 真实趋势 & Learning Engine 状态
# ============================================================

def phage_trend_7d():
    """
    最近 7 天新增噬菌体数（按 created_at 聚合，含补零天）。
    返回 (days_labels, values) 二元组，days_labels 形如 ['10/06', ...]。
    """
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=6)

    rows = _run("""
        MATCH (p:Phage)
        WHERE p.created_at IS NOT NULL
        WITH date(p.created_at) AS d, count(*) AS n
        WHERE d >= date($since)
        RETURN toString(d) AS day, n
    """, since=since.isoformat())

    by_day = {r["day"]: r["n"] for r in rows}

    days, vals = [], []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        days.append(d.strftime("%m/%d"))
        vals.append(by_day.get(d.isoformat(), 0))
    return days, vals


def learning_engine_status() -> Dict:
    """
    Learning Engine 三条链路的真实计数：
      - reuse_events       : KnowledgeReuseEvent 总数
      - case_linked        : 已挂 SOURCE_CASE 的复用事件数
      - pkg_linked         : 已挂 TARGETS_PACKAGE 的复用事件数
      - approved_pkgs      : 已审核通过的证据包数
      - total_pkgs         : 证据包总数
    """
    with get_driver().session() as s:
        def one(cypher):
            r = s.run(cypher).single()
            return r[0] if r else 0
        return {
            "reuse_events": one("MATCH (k:KnowledgeReuseEvent) RETURN count(k)"),
            "case_linked": one("""
                MATCH (k:KnowledgeReuseEvent)-[:SOURCE_CASE]->(:ClinicalCase)
                RETURN count(DISTINCT k)
            """),
            "pkg_linked": one("""
                MATCH (k:KnowledgeReuseEvent)-[:TARGETS_PACKAGE]->(:ScientificEvidencePackage)
                RETURN count(DISTINCT k)
            """),
            "approved_pkgs": one("""
                MATCH (p:ScientificEvidencePackage)
                WHERE coalesce(p.review_status, p.status) = 'approved'
                RETURN count(p)
            """),
            "total_pkgs": one("MATCH (p:ScientificEvidencePackage) RETURN count(p)"),
        }


def dataset_counts() -> Dict:
    """数据导入页：各数据集实时记录数（key = 节点标签）"""
    with get_driver().session() as s:
        def one(label):
            r = s.run(f"MATCH (n:{label}) RETURN count(n)").single()
            return r[0] if r else 0
        return {
            "Phage":        one("Phage"),
            "ClinicalCase": one("ClinicalCase"),
            "LysisAssay":   one("LysisAssay"),
            "Organization": one("Organization"),
        }