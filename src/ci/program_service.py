# src/ci/program_service.py
"""
DevelopmentProgram / ClinicalTrial / ClinicalIndication / ProductAsset
合并服务（PRD 5.2 / 7.2 / 8.1）

包含四个部分：
    Part 1: DevelopmentProgram   —— 研发项目
    Part 2: ClinicalTrial        —— 临床试验
    Part 3: ClinicalIndication   —— 临床适应症
    Part 4: ProductAsset         —— 产品资产
"""

# ==================================================================
# Part 1: DevelopmentProgram (原 program_service.py)
# ==================================================================
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event
from src.shared.evidence_source import get_or_create_pathogen


def generate_program_id() -> str:
    """生成研发项目 ID（格式：CI:PROG:XXXXXXXX）。"""
    return f"CI:PROG:{uuid.uuid4().hex[:8].upper()}"


def create_development_program(
    driver: Driver,
    organization_id: str,
    canonical_name: str,
    program_type: str = "therapeutic",
    development_stage: str = "discovery",
    modality: Optional[str] = None,
    target_pathogen_species: Optional[List[str]] = None,
    strategy_ids: Optional[List[str]] = None,
    actor_id: str = "system",
) -> str:
    """
    创建研发项目（DevelopmentProgram）。

    - 校验组织存在
    - 创建项目节点并建立 DEVELOPS 关系
    - 关联目标病原（TARGETS_PATHOGEN）
    - 关联工程策略（USES_STRATEGY）

    Args:
        organization_id: 所属组织
        canonical_name: 项目规范名称
        program_type: 项目类型（therapeutic / diagnostic / platform / research）
        development_stage: 发展阶段
        modality: 模态（natural_phage / engineered_phage / cocktail）
        target_pathogen_species: 目标病原物种列表
        strategy_ids: 工程策略 ID 列表
        actor_id: 操作者

    Returns:
        str: program_id
    """
    target_pathogen_species = target_pathogen_species or []
    strategy_ids = strategy_ids or []
    prog_id = generate_program_id()

    with driver.session() as session:
        # 校验组织
        org_check = session.run(
            "MATCH (o:Organization {organization_id: $oid}) RETURN o",
            oid=organization_id,
        ).single()
        if not org_check:
            raise ValueError(f"组织 {organization_id} 不存在")

        # 创建项目节点 + DEVELOPS 关系
        session.run(
            """
            CREATE (d:DevelopmentProgram {
                program_id: $prog_id,
                canonical_name: $name,
                program_type: $p_type,
                development_stage: $stage,
                modality: $modality,
                program_status: 'active',
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
            WITH d
            MATCH (o:Organization {organization_id: $oid})
            CREATE (o)-[:DEVELOPS]->(d)
            """,
            prog_id=prog_id, name=canonical_name, p_type=program_type,
            stage=development_stage, modality=modality, oid=organization_id,
        )

        # 关联目标病原
        for species in target_pathogen_species:
            pathogen_id = get_or_create_pathogen(
                driver, species=species, actor_id=actor_id,
            )
            session.run(
                """
                MATCH (d:DevelopmentProgram {program_id: $prog_id})
                MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                MERGE (d)-[:TARGETS_PATHOGEN]->(p)
                """,
                prog_id=prog_id, pathogen_id=pathogen_id,
            )

        # 关联工程策略
        for sid in strategy_ids:
            es_chk = session.run(
                "MATCH (es:EngineeringStrategy {strategy_id: $sid}) RETURN es LIMIT 1",
                sid=sid,
            ).single()
            if not es_chk:
                print(f"⚠️ EngineeringStrategy {sid} 不存在，跳过 USES_STRATEGY")
                continue
            session.run(
                """
                MATCH (d:DevelopmentProgram {program_id: $prog_id})
                MATCH (es:EngineeringStrategy {strategy_id: $sid})
                MERGE (d)-[:USES_STRATEGY]->(es)
                """,
                prog_id=prog_id, sid=sid,
            )

        write_audit_event(
            driver, action_type="CREATE",
            object_type="DevelopmentProgram", object_id=prog_id,
            actor_id=actor_id,
            delta={
                "canonical_name": canonical_name,
                "organization_id": organization_id,
                "target_pathogen_species": target_pathogen_species,
                "strategy_ids": strategy_ids,
            },
            reason=f"创建研发项目: {canonical_name}",
        )
        return prog_id


def link_program_to_strategy(driver, program_id, strategy_id, actor_id="system"):
    """
    为已有项目关联工程策略（幂等）。
    """
    with driver.session() as s:
        d = s.run("MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d LIMIT 1",
                  pid=program_id).single()
        if not d:
            raise ValueError(f"DevelopmentProgram {program_id} 不存在")
        es = s.run("MATCH (es:EngineeringStrategy {strategy_id: $sid}) RETURN es LIMIT 1",
                   sid=strategy_id).single()
        if not es:
            raise ValueError(f"EngineeringStrategy {strategy_id} 不存在")

        existing = s.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})-[:USES_STRATEGY]->(es:EngineeringStrategy {strategy_id: $sid})
            RETURN 1 AS x LIMIT 1
            """,
            pid=program_id, sid=strategy_id,
        ).single()
        if existing:
            return True

        s.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (es:EngineeringStrategy {strategy_id: $sid})
            MERGE (d)-[:USES_STRATEGY]->(es)
            """,
            pid=program_id, sid=strategy_id,
        )
    write_audit_event(
        driver, action_type="LINK_CREATE",
        object_type="DevelopmentProgram", object_id=program_id,
        actor_id=actor_id,
        delta={"relation": "USES_STRATEGY", "strategy_id": strategy_id},
        reason=f"项目 {program_id} 关联策略 {strategy_id}",
    )
    return True


def backfill_program_uses_strategy(driver, actor_id="backfill"):
    """
    回填 USES_STRATEGY 关系：
    从 (项目)<-ASSOCIATED_WITH-(构建体)-IMPLEMENTS->(策略) 推导。
    """
    created = 0
    details = []
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (d:DevelopmentProgram)<-[:ASSOCIATED_WITH]-(ec:EngineeredPhageConstruct)
                  -[:IMPLEMENTS]->(es:EngineeringStrategy)
            WHERE NOT (d)-[:USES_STRATEGY]->(es)
            RETURN DISTINCT d.program_id AS pid, es.strategy_id AS sid
        """))
        for r in rows:
            s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MATCH (es:EngineeringStrategy {strategy_id: $sid})
                MERGE (d)-[:USES_STRATEGY]->(es)
            """, pid=r["pid"], sid=r["sid"])
            created += 1
            details.append({"program_id": r["pid"], "strategy_id": r["sid"]})

    if created > 0:
        write_audit_event(
            driver, action_type="LINK_CREATE",
            object_type="DevelopmentProgram", object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_usES_STRATEGY": created, "details": details},
            reason=f"回填 USES_STRATEGY 关系：{created} 条",
        )
    return {"created": created, "details": details}


def update_program_status(driver, program_id, new_status, source_event_id, actor_id):
    """
    更新项目状态，并关联到触发事件（AFFECTS）。
    """
    with driver.session() as session:
        old = session.run(
            "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d.program_status AS status",
            pid=program_id,
        ).single()
        if not old:
            raise ValueError(f"项目 {program_id} 不存在")

        session.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            SET d.program_status = $new_status, d.updated_at = datetime()
            """,
            pid=program_id, new_status=new_status,
        )
        session.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (e:IntelligenceEvent {event_id: $source_event_id})
            MERGE (e)-[:AFFECTS]->(d)
            """,
            pid=program_id, source_event_id=source_event_id,
        )
        write_audit_event(
            driver, action_type="STATUS_CHANGE",
            object_type="DevelopmentProgram", object_id=program_id,
            actor_id=actor_id,
            delta={"status": {"before": old["status"], "after": new_status}},
            reason=f"项目状态从 {old['status']} 更新为 {new_status}",
        )


# ==================================================================
# Part 2: ClinicalTrial (原 clinical_trial_service.py)
# ==================================================================

# 受控词表：临床试验阶段
TRIAL_PHASES = {
    "preclinical", "phase_1", "phase_1_2", "phase_2",
    "phase_2b", "phase_3", "phase_4", "unknown",
}
# 受控词表：临床试验状态
TRIAL_STATUSES = {
    "not_yet_recruiting", "recruiting", "active",
    "completed", "terminated", "suspended", "withdrawn", "unknown",
}


def generate_trial_id() -> str:
    """生成临床试验 ID（格式：CI:TRIAL:XXXXXXXX）。"""
    return f"CI:TRIAL:{uuid.uuid4().hex[:8].upper()}"


def create_clinical_trial(
    driver: Driver,
    title: str,
    nct_id: Optional[str] = None,
    phase: str = "unknown",
    status: str = "unknown",
    indication: Optional[str] = None,
    sponsor: Optional[str] = None,
    organization_id: Optional[str] = None,
    program_id: Optional[str] = None,
    start_date: Optional[str] = None,
    completion_date: Optional[str] = None,
    enrollment: Optional[int] = None,
    primary_endpoint: Optional[str] = None,
    source_url: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    创建临床试验。

    - 若 nct_id 已存在，返回已有 ID（幂等）
    - 建立 HAS_TRIAL（项目）和 SPONSORS（组织）关系
    """
    if phase not in TRIAL_PHASES:
        raise ValueError(f"phase 必须是 {TRIAL_PHASES} 之一")
    if status not in TRIAL_STATUSES:
        raise ValueError(f"status 必须是 {TRIAL_STATUSES} 之一")

    trial_id = generate_trial_id()
    with driver.session() as session:
        # 幂等：nct_id 查重
        if nct_id:
            existing = session.run("""
                MATCH (ct:ClinicalTrial {nct_id: $nct})
                RETURN ct.trial_id AS id LIMIT 1
            """, nct=nct_id).single()
            if existing:
                print(f"ℹ️ 临床试验 {nct_id} 已存在: {existing['id']}")
                return existing["id"]

        session.run("""
            CREATE (ct:ClinicalTrial {
                trial_id: $tid, nct_id: $nct_id, title: $title,
                phase: $phase, status: $status, indication: $indication,
                sponsor: $sponsor, start_date: $start_date,
                completion_date: $completion_date, enrollment: $enrollment,
                primary_endpoint: $primary_endpoint, source_url: $source_url,
                review_status: 'pending',
                last_verified_at: datetime(),
                created_at: datetime(), updated_at: datetime()
            })
        """, tid=trial_id, nct_id=nct_id, title=title, phase=phase,
             status=status, indication=indication, sponsor=sponsor,
             start_date=start_date, completion_date=completion_date,
             enrollment=enrollment, primary_endpoint=primary_endpoint,
             source_url=source_url)

        # 关联项目
        if program_id:
            session.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MATCH (ct:ClinicalTrial {trial_id: $tid})
                MERGE (d)-[:HAS_TRIAL]->(ct)
            """, pid=program_id, tid=trial_id)
        # 关联组织
        if organization_id:
            session.run("""
                MATCH (o:Organization {organization_id: $oid})
                MATCH (ct:ClinicalTrial {trial_id: $tid})
                MERGE (o)-[:SPONSORS]->(ct)
            """, oid=organization_id, tid=trial_id)

        write_audit_event(
            driver, action_type="CREATE",
            object_type="ClinicalTrial", object_id=trial_id,
            actor_id=actor_id,
            delta={"nct_id": nct_id, "phase": phase, "status": status, "sponsor": sponsor},
            reason=f"创建临床试验: {title[:60]}",
        )
    return trial_id


def get_clinical_trial(driver, trial_id):
    """按 ID 查询临床试验，附带项目和赞助方。"""
    with driver.session() as session:
        r = session.run("""
            MATCH (ct:ClinicalTrial {trial_id: $tid})
            OPTIONAL MATCH (d:DevelopmentProgram)-[:HAS_TRIAL]->(ct)
            OPTIONAL MATCH (o:Organization)-[:SPONSORS]->(ct)
            RETURN ct,
                   collect(DISTINCT d.canonical_name) AS programs,
                   collect(DISTINCT o.canonical_name) AS sponsors
        """, tid=trial_id).single()
        if not r:
            return None
        data = dict(r["ct"])
        data["programs"] = r["programs"]
        data["sponsors"] = r["sponsors"]
        return data


def list_trials_for_program(driver, program_id):
    """列出某项目的所有临床试验。"""
    with driver.session() as session:
        r = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})-[:HAS_TRIAL]->(ct:ClinicalTrial)
            OPTIONAL MATCH (o:Organization)-[:SPONSORS]->(ct)
            RETURN ct.trial_id AS id, ct.nct_id AS nct_id, ct.title AS title,
                   ct.phase AS phase, ct.status AS status, ct.start_date AS start_date,
                   collect(DISTINCT o.canonical_name) AS sponsors
            ORDER BY ct.start_date DESC
        """, pid=program_id)
        return [dict(rec) for rec in r]


def list_trials_for_organization(driver, organization_id):
    """列出某组织赞助的所有临床试验。"""
    with driver.session() as session:
        r = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:SPONSORS]->(ct:ClinicalTrial)
            RETURN ct.trial_id AS id, ct.nct_id AS nct_id, ct.title AS title,
                   ct.phase AS phase, ct.status AS status
            ORDER BY ct.start_date DESC
        """, oid=organization_id)
        return [dict(rec) for rec in r]


# ==================================================================
# Part 3: ClinicalIndication (原 indication_service.py)
# ==================================================================

def generate_indication_id() -> str:
    """生成临床适应症 ID（格式：CI:IND:XXXXXXXX）。"""
    return f"CI:IND:{uuid.uuid4().hex[:8].upper()}"


def create_indication(
    driver, name: str, infection_site=None, pathogen_scope=None,
    disease_stage=None, standard_term=None, actor_id="system",
) -> str:
    """
    创建临床适应症（幂等：按 name 忽略大小写查重）。
    """
    if not name or not name.strip():
        raise ValueError("name 不能为空")
    name = name.strip()

    with driver.session() as s:
        existing = s.run("""
            MATCH (ci:ClinicalIndication)
            WHERE toLower(ci.name) = toLower($name)
            RETURN ci.indication_id AS iid LIMIT 1
        """, name=name).single()
        if existing:
            return existing["iid"]

        indication_id = generate_indication_id()
        s.run("""
            CREATE (ci:ClinicalIndication {
                indication_id: $iid, name: $name,
                infection_site: $site, pathogen_scope: $scope,
                disease_stage: $stage, standard_term: $term,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
        """, iid=indication_id, name=name, site=infection_site,
             scope=pathogen_scope, stage=disease_stage, term=standard_term)

    write_audit_event(
        driver, action_type="CREATE",
        object_type="ClinicalIndication", object_id=indication_id,
        actor_id=actor_id, delta={"name": name},
        reason=f"创建适应症: {name}",
    )
    return indication_id


def link_program_to_indication(driver, program_id, indication_id, actor_id="system"):
    """建立 (项目)-[:ADDRESSES]->(适应症) 关系。"""
    with driver.session() as s:
        ok = s.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (ci:ClinicalIndication {indication_id: $iid})
            MERGE (d)-[:ADDRESSES]->(ci)
            RETURN d.canonical_name AS pname, ci.name AS iname
        """, pid=program_id, iid=indication_id).single()
        if not ok:
            raise ValueError("program 或 indication 不存在")

    write_audit_event(
        driver, action_type="LINK_CREATE",
        object_type="ClinicalIndication", object_id=indication_id,
        actor_id=actor_id, delta={"program_id": program_id},
        reason=f"项目 {ok['pname']} 关联适应症 {ok['iname']}",
    )
    return True


def list_indications(driver, limit=100):
    """列出所有适应症，附带关联项目数。"""
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (ci:ClinicalIndication)
            OPTIONAL MATCH (d:DevelopmentProgram)-[:ADDRESSES]->(ci)
            RETURN ci.indication_id AS indication_id, ci.name AS name,
                   ci.infection_site AS infection_site,
                   ci.pathogen_scope AS pathogen_scope,
                   ci.disease_stage AS disease_stage,
                   ci.standard_term AS standard_term,
                   ci.review_status AS review_status,
                   count(DISTINCT d) AS program_count
            ORDER BY ci.name LIMIT $limit
        """, limit=limit))
    return [dict(r) for r in rows]


# ==================================================================
# Part 4: ProductAsset (原 product_asset_service.py)
# ==================================================================

ASSET_TYPES = {"drug", "diagnostic", "platform", "software", "service", "other"}
ASSET_STATUSES = {"discovery", "preclinical", "clinical", "approved",
                  "commercial", "discontinued", "unknown"}


def generate_asset_id() -> str:
    """生成产品资产 ID（格式：CI:ASSET:XXXXXXXX）。"""
    return f"CI:ASSET:{uuid.uuid4().hex[:8].upper()}"


def create_product_asset(
    driver, name, organization_id, asset_type="drug", status="unknown",
    based_on_program_id=None, description=None, actor_id="system",
) -> str:
    """
    创建产品资产（幂等：同一组织下同名资产返回已有 ID）。
    """
    if not name or not name.strip():
        raise ValueError("name 不能为空")
    name = name.strip()
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type 必须是 {sorted(ASSET_TYPES)} 之一")
    if status not in ASSET_STATUSES:
        raise ValueError(f"status 必须是 {sorted(ASSET_STATUSES)} 之一")

    with driver.session() as s:
        # 校验组织
        org_ok = s.run(
            "MATCH (o:Organization {organization_id: $oid}) RETURN o.canonical_name AS n LIMIT 1",
            oid=organization_id,
        ).single()
        if not org_ok:
            raise ValueError(f"Organization {organization_id} 不存在")

        # 幂等检查
        existing = s.run("""
            MATCH (o:Organization {organization_id: $oid})-[:OWNS_ASSET]->(a:ProductAsset)
            WHERE toLower(a.name) = toLower($name)
            RETURN a.asset_id AS aid LIMIT 1
        """, oid=organization_id, name=name).single()
        if existing:
            return existing["aid"]

        asset_id = generate_asset_id()
        s.run("""
            MATCH (o:Organization {organization_id: $oid})
            CREATE (a:ProductAsset {
                asset_id: $aid, name: $name, asset_type: $atype,
                status: $status, description: $desc,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
            CREATE (o)-[:OWNS_ASSET]->(a)
        """, oid=organization_id, aid=asset_id, name=name,
             atype=asset_type, status=status, desc=description)

        # 可选：关联基础项目
        if based_on_program_id:
            s.run("""
                MATCH (a:ProductAsset {asset_id: $aid})
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MERGE (a)-[:BASED_ON]->(d)
            """, aid=asset_id, pid=based_on_program_id)

    write_audit_event(
        driver, action_type="CREATE",
        object_type="ProductAsset", object_id=asset_id,
        actor_id=actor_id,
        delta={"name": name, "organization_id": organization_id, "asset_type": asset_type},
        reason=f"创建产品资产: {name}",
    )
    return asset_id


def list_product_assets(driver, organization_id=None, limit=100):
    """列出产品资产（可按组织过滤）。"""
    with driver.session() as s:
        if organization_id:
            rows = list(s.run("""
                MATCH (o:Organization {organization_id: $oid})-[:OWNS_ASSET]->(a:ProductAsset)
                OPTIONAL MATCH (a)-[:BASED_ON]->(d:DevelopmentProgram)
                RETURN a.asset_id AS asset_id, a.name AS name,
                       a.asset_type AS asset_type, a.status AS status,
                       o.canonical_name AS organization,
                       collect(DISTINCT d.canonical_name) AS programs
                ORDER BY a.name LIMIT $limit
            """, oid=organization_id, limit=limit))
        else:
            rows = list(s.run("""
                MATCH (o:Organization)-[:OWNS_ASSET]->(a:ProductAsset)
                OPTIONAL MATCH (a)-[:BASED_ON]->(d:DevelopmentProgram)
                RETURN a.asset_id AS asset_id, a.name AS name,
                       a.asset_type AS asset_type, a.status AS status,
                       o.canonical_name AS organization,
                       collect(DISTINCT d.canonical_name) AS programs
                ORDER BY a.name LIMIT $limit
            """, limit=limit))
    return [dict(r) for r in rows]