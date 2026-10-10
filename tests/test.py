# tests/test.py
import sys
from pathlib import Path

# 把项目根目录加进 sys.path（如果你已有 conftest.py，可以删掉这 3 行）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_driver

from src.decision_support.decision_brief import (
    create_decision_brief,
    get_decision_brief,
)
from src.decision_support.intelligence_question import (
    create_intelligence_question,
    link_brief_to_question,
    get_intelligence_question,
)
from src.decision_support.decision_record import create_decision_record


# ---- 初始化 Neo4j driver ----
driver = get_driver()


# ---- 1. 创建一个 IntelligenceQuestion ----
qid = create_intelligence_question(
    driver,
    question_text="是否应优先评估针对 CRKP 的尾纤维工程策略？",
    question_type="technology",
    requester_id="analyst_zhang",
)
print("QID:", qid)

# ---- 2. 创建 DecisionBrief ----
bid = create_decision_brief(
    driver,
    brief_type="technology",
    title="尾纤维工程策略优先级评估",
    executive_summary="基于当前公开证据，尾纤维工程在 CRKP 宿主范围扩展上有多篇论文支持...",
    key_facts=[
        {"text": "BiomX 公开管线中已布局 tail fiber 方向", "source_object_id": "CI:EVT:DEMO"},
    ],
    uncertainties=["国内是否有同方向项目尚不明确"],
    recommended_next_steps=["启动可行性评估", "安排 IP FTO 初筛"],
    generated_by="analyst",
    as_of_date="2026-10-09",
    question_id=qid,
)
print("BID:", bid)

# ---- 3. 手动关联 brief → question（幂等，重复建也不报错）----
link_brief_to_question(driver, brief_id=bid, question_id=qid)

# ---- 4. 基于 DecisionBrief 创建 DecisionRecord ----
did = create_decision_record(
    driver,
    brief_id=bid,
    decision_type="evaluate",
    decision_summary="启动尾纤维工程策略可行性评估",
    rationale="基于 DecisionBrief 的技术证据与不确定性",
    decision_owner="VP_RD",
)
print("DID:", did)

# ---- 5. 顺便验证下 get_intelligence_question（消掉 IDE 的黄线）----
print("IQ:", get_intelligence_question(driver, qid))

# ---- MCI-12 多来源事件合并验证 ----
from src.ci.organization_service import create_organization
from src.ci.event_service import capture_intelligence_event
from src.shared.source_artifact_service import create_source_artifact

# 组织
try:
    oid = create_organization(driver, canonical_name="MergeTest Corp", actor_id="test")
except ValueError:
    with driver.session() as s:
        r = s.run(
            "MATCH (o:Organization {canonical_name: $n}) RETURN o.organization_id AS id",
            n="MergeTest Corp",
        ).single()
        oid = r["id"]
print("ORG:", oid)

# 两个不同的 SourceArtifact（模拟两个来源报道同一事件）
src1 = create_source_artifact(
    driver, source_type="press_release",
    title="Source A - BiomX acquires APT",
    url="https://example.com/source-a",
    published_date="2026-10-01",
    actor_id="test",
)
src2 = create_source_artifact(
    driver, source_type="news_article",
    title="Source B - BiomX acquires APT (coverage)",
    url="https://example.com/source-b",
    published_date="2026-10-02",
    actor_id="test",
)
print("SRC1:", src1, "SRC2:", src2)

# 第一次：新建事件
eid1 = capture_intelligence_event(
    driver,
    event_type="acquisition",
    title="BiomX acquires APT (merge test)",
    factual_summary="First report from Source A",
    organization_id=oid,
    event_date="2026-10-01",
    source_ids=[src1],
    actor_id="test",
)
print("EID1 (create):", eid1)

# 第二次：同 key，应该合并而不是抛错
eid2 = capture_intelligence_event(
    driver,
    event_type="acquisition",
    title="BiomX acquires APT (merge test)",
    factual_summary="Second report from Source B",
    organization_id=oid,
    event_date="2026-10-01",
    source_ids=[src2],
    actor_id="test",
)
print("EID2 (merge):", eid2)

assert eid1 == eid2, "应该返回同一个 event_id"

with driver.session() as s:
    r = s.run(
        """
        MATCH (e:IntelligenceEvent {event_id: $eid})-[:HAS_SOURCE]->(s:SourceArtifact)
        RETURN collect(s.source_id) AS sources
        """,
        eid=eid1,
    ).single()
    print("HAS_SOURCE:", r["sources"])
    assert set(r["sources"]) == {src1, src2}, "两个来源都应该挂到同一个事件"
    print("✅ MCI-12 多来源合并通过")

    # ---- 验证：事件都有 organization_id 属性 ----
with driver.session() as s:
    r = s.run("""
        MATCH (e:IntelligenceEvent)
        WHERE e.organization_id IS NULL
        RETURN count(e) AS missing
    """).single()
    print("事件缺 organization_id:", r["missing"])
    assert r["missing"] == 0, "有事件没写 organization_id"

# ---- 验证：不存在 CONCERNS 关系 ----
with driver.session() as s:
    r = s.run("""
        MATCH (e:IntelligenceEvent)-[:CONCERNS]->(:Organization)
        RETURN count(e) AS old_concerns
    """).single()
    print("残留 CONCERNS:", r["old_concerns"])
    assert r["old_concerns"] == 0, "仍有 CONCERNS 关系"

# ---- 验证：SourceArtifact url 唯一，没有重复 ----
with driver.session() as s:
    r = s.run("""
        MATCH (s:SourceArtifact)
        WITH s.url AS url, count(*) AS cnt
        WHERE url IS NOT NULL AND cnt > 1
        RETURN count(*) AS dup_urls
    """).single()
    print("重复 url 数:", r["dup_urls"])
    assert r["dup_urls"] == 0, "存在重复 url 的 SourceArtifact"

print("✅ P0-3 / P0-4 通过")

from src.ci.organization_service import create_organization
from src.ci.entity_resolution_service import (
    link_partnership,
    list_partnerships,
    link_organizations,
    list_organization_relations,
)

def _get_or_create_org(driver, name):
    from src.ci.organization_service import get_organization_by_name
    existing = get_organization_by_name(driver, name)
    if existing:
        # get_organization_by_name 返回 list of Node
        return existing[0]["organization_id"]
    return create_organization(driver, canonical_name=name, actor_id="test")

# 准备两个组织
oid_a = _get_or_create_org(driver, "P1-A Corp")
oid_b = _get_or_create_org(driver, "P1-B Corp")
oid_c = _get_or_create_org(driver, "P1-C Corp")
print("ORG_A:", oid_a)
print("ORG_B:", oid_b)
print("ORG_C:", oid_c)

# 建合作
pid = link_partnership(
    driver, oid_a, oid_b,
    partnership_type="partner_with",
    note="联合开发噬菌体鸡尾酒",
    direction="symmetric",
)
print("PARTNERSHIP:", pid)

# 建控制
rid = link_organizations(driver, oid_a, oid_c, relation_type="subsidiary_of", note="全资子公司")
print("OWNS_OR_CONTROLS:", rid)

# 查询
print("PARTNERSHIPS of A:", list_partnerships(driver, oid_a))
print("OWNS_OR_CONTROLS of A:", list_organization_relations(driver, oid_a))

# 断言
ps = list_partnerships(driver, oid_a)
assert any(p["partnership_id"] == pid for p in ps), "PARTNERS_WITH 未建立"
assert len([p for p in ps if p["partnership_id"] == pid]) == 2, "symmetric 应有两条边"

rel = list_organization_relations(driver, oid_a)
assert any(r["relation_id"] == rid for r in rel), "OWNS_OR_CONTROLS 未建立"

print("✅ P1-5 PARTNERS_WITH 通过")

# ---- P1-6 验证 ----
print("\n===== P1-6 验证 =====")
from src.ci.program_service import (
    link_program_to_strategy,
    backfill_program_uses_strategy,
)

# 1. 手动建一条 USES_STRATEGY
with driver.session() as s:
    r = s.run("""
        MATCH (d:DevelopmentProgram) RETURN d.program_id AS pid LIMIT 1
    """).single()
    pid = r["pid"] if r else None
    r = s.run("""
        MATCH (es:EngineeringStrategy) RETURN es.strategy_id AS sid LIMIT 1
    """).single()
    sid = r["sid"] if r else None

if pid and sid:
    print(f"试挂: {pid} → {sid}")
    link_program_to_strategy(driver, pid, sid, actor_id="test")
else:
    print("⚠️ 库里还没有 program 或 strategy，跳过 link 测试")

# 2. backfill
bf = backfill_program_uses_strategy(driver, actor_id="test_backfill")
print(f"backfill 新增: {bf['created']} 条")

# 3. 查询验证
with driver.session() as s:
    total = s.run("""
        MATCH (:DevelopmentProgram)-[:USES_STRATEGY]->(:EngineeringStrategy)
        RETURN count(*) AS c
    """).single()["c"]
    print(f"USES_STRATEGY 总条数: {total}")
    assert total >= 1 or (pid is None or sid is None), "USES_STRATEGY 未建立"

print("✅ P1-6 USES_STRATEGY 通过")

# ---- P1-7 验证 ----
print("\n===== P1-7 验证 =====")
from src.engineering_intelligence.construct_service import (
    link_construct_to_organization,
    backfill_construct_developed_by,
)

# 1. 手动挂一条
with driver.session() as s:
    r = s.run("""
        MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
              <-[:DEVELOPS]-(o:Organization)
        RETURN ec.construct_id AS cid, o.organization_id AS oid LIMIT 1
    """).single()
    if r:
        cid, oid = r["cid"], r["oid"]
        print(f"试挂: {cid} → {oid}")
        link_construct_to_organization(driver, cid, oid, actor_id="test")
    else:
        print("⚠️ 库里还没有 construct 关联到 program + org，跳过 link 测试")

# 2. backfill
bf = backfill_construct_developed_by(driver, actor_id="test_backfill")
print(f"backfill 新增: {bf['created']} 条")

# 3. 查询验证
with driver.session() as s:
    total = s.run("""
        MATCH (:EngineeredPhageConstruct)-[:DEVELOPED_BY]->(:Organization)
        RETURN count(*) AS c
    """).single()["c"]
    print(f"DEVELOPED_BY 总条数: {total}")

    gaps = s.run("""
        MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
              <-[:DEVELOPS]-(o:Organization)
        WHERE NOT (ec)-[:DEVELOPED_BY]->(o)
        RETURN count(DISTINCT ec) AS c
    """).single()["c"]
    print(f"仍有缺口的 construct 数: {gaps}")
    assert gaps == 0, f"仍有 {gaps} 个 construct 缺 DEVELOPED_BY"

print("✅ P1-7 DEVELOPED_BY 通过")

# ---- P1-8 验证 ----
print("\n===== P1-8 验证 =====")
from src.engineering_intelligence.claim_extractor import (
    link_result_to_claim,
    backfill_result_to_claim,
    get_verdicts_for_claim,
)

# 1. 手动建一条 result 关联 claim
with driver.session() as s:
    r = s.run("""
        MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
              <-[:CLAIMS_ABOUT]-(tc:TechnicalClaim)
        WHERE tr.result_type = tc.claim_type
          AND tr.outcome_direction IN ['positive','negative']
        RETURN tr.result_id AS rid, tc.claim_id AS cid LIMIT 1
    """).single()
    if r:
        rid, cid = r["rid"], r["cid"]
        print(f"试挂: {rid} → {cid}")
        link_result_to_claim(driver, rid, cid, actor_id="test")
    else:
        print("⚠️ 库里没有可挂的 result/claim 组合，跳过 link 测试")

# 2. backfill
bf = backfill_result_to_claim(driver, actor_id="test_backfill")
print(f"backfill 新增: {bf['created']} 条")

# 3. 查询验证
with driver.session() as s:
    total = s.run("""
        MATCH (:TechnicalResult)-[:SUPPORTED_OR_CHALLENGES]->(:TechnicalClaim)
        RETURN count(*) AS c
    """).single()["c"]
    print(f"SUPPORTED_OR_CHALLENGES 总条数: {total}")

    # 反向验证：不应该有 result_type 匹配但方向对不上却依然缺关系的
    gaps = s.run("""
        MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
              <-[:CLAIMS_ABOUT]-(tc:TechnicalClaim)
        WHERE tr.result_type = tc.claim_type
          AND tr.outcome_direction IN ['positive','negative']
          AND NOT (tr)-[:SUPPORTED_OR_CHALLENGES]->(tc)
        RETURN count(*) AS c
    """).single()["c"]
    print(f"仍有缺口的组合数: {gaps}")
    assert gaps == 0, f"仍有 {gaps} 个 (result, claim) 组合没挂 SUPPORTED_OR_CHALLENGES"

# 4. 若刚才手动挂过，查一下 verdict
if r:
    vs = get_verdicts_for_claim(driver, cid)
    print(f"claim {cid} 的判定历史: {len(vs)} 条")
    for v in vs[:3]:
        print(f"   {v['result_id']} --[{v['verdict']}]--> ({v['outcome_direction']})")

print("✅ P1-8 SUPPORTED_OR_CHALLENGES 通过")

# ---- P1-9 验证 ----
print("\n===== P1-9 验证 =====")
from src.engineering_intelligence.technology_assessment import (
    create_technology_assessment,
    get_assessments_for_claim,
    backfill_claim_evaluated_by,
)

# 找一个已有的 claim 试试
with driver.session() as s:
    r = s.run("""
        MATCH (tc:TechnicalClaim)
        RETURN tc.claim_id AS cid LIMIT 1
    """).single()

if r:
    cid = r["cid"]
    # 1. 建一个针对 claim 的 TechnologyAssessment
    ta_id = create_technology_assessment(
        driver,
        subject_type="claim",
        subject_id=cid,
        evidence_maturity="in_vitro",
        technical_relevance="medium",
        assessment_summary="演示：针对 claim 的技术评估",
        actor_id="test",
    )
    print(f"TA (claim): {ta_id}")

    # 2. 查询
    assessments = get_assessments_for_claim(driver, cid)
    print(f"claim {cid} 的评估数: {len(assessments)}")
    assert len(assessments) >= 1, "claim 没有 technology assessment"
else:
    print("⚠️ 库里没有 TechnicalClaim，跳过 claim 评估测试")

# 3. backfill
bf = backfill_claim_evaluated_by(driver, actor_id="test_backfill")
print(f"backfill 新增 EVALUATED_BY: {bf['created']} 条")

# 4. 查询验证
with driver.session() as s:
    total = s.run("""
        MATCH (:TechnicalClaim)-[:EVALUATED_BY]->(:TechnologyAssessment)
        RETURN count(*) AS c
    """).single()["c"]
    print(f"EVALUATED_BY 总条数: {total}")

    # 期望 0
    gaps = s.run("""
        MATCH (ta:TechnologyAssessment {subject_type: 'claim'})-[:ASSESSES]->(tc:TechnicalClaim)
        WHERE NOT (tc)-[:EVALUATED_BY]->(ta)
        RETURN count(*) AS c
    """).single()["c"]
    print(f"仍有缺口的组合数: {gaps}")
    assert gaps == 0, f"仍有 {gaps} 个 claim 评估缺 EVALUATED_BY"

print("✅ P1-9 claim 类型技术评估 通过")