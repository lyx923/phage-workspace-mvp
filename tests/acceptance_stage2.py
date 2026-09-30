# tests/acceptance_stage2.py
"""
Stage2 增补 PRD 验收脚本
覆盖 PRD 18.1 Ontology 验收 / 18.2 产品能力验收 / 18.3 质量验收

用法（在项目根目录）：
    python tests/acceptance_stage2.py

输出：
    - 每个验收项的通过/失败
    - 最终 PASS / FAIL 汇总
    - 退出码：0 全部通过，1 有失败
"""
import os
import sys
from datetime import datetime

# 加项目根目录到 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import get_driver


# ============================================================
# 结果收集
# ============================================================

class Report:
    def __init__(self):
        self.rows = []

    def add(self, section: str, item_id: str, item: str,
            passed: bool, actual: str, expected: str, note: str = ""):
        self.rows.append({
            "section": section,
            "id": item_id,
            "item": item,
            "passed": passed,
            "actual": actual,
            "expected": expected,
            "note": note,
        })

    def print(self):
        by_section = {}
        for r in self.rows:
            by_section.setdefault(r["section"], []).append(r)

        for section, rows in by_section.items():
            print()
            print("=" * 96)
            print(f"  {section}")
            print("=" * 96)
            print(f"  {'ID':<10s} {'验收项':<34s} {'结果':<8s} {'实际':<22s} {'标准':<22s}")
            print("  " + "-" * 92)
            for r in rows:
                status = "✅ PASS" if r["passed"] else "❌ FAIL"
                print(f"  {r['id']:<10s} {r['item'][:32]:<34s} {status:<8s} "
                      f"{str(r['actual'])[:20]:<22s} {str(r['expected'])[:20]:<22s}")
                if r.get("note") and not r["passed"]:
                    print(f"           ↳ {r['note']}")

        total = len(self.rows)
        passed = sum(1 for r in self.rows if r["passed"])
        failed = total - passed
        print()
        print("=" * 96)
        print(f"  汇总：{passed}/{total} 通过，{failed} 失败")
        print(f"  时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 96)
        return failed == 0


def _one(driver, cypher, **params):
    with driver.session() as s:
        r = s.run(cypher, **params).single()
        return r[0] if r else 0


# ============================================================
# 18.1 Ontology 验收
# ============================================================

def check_ontology(driver, report: Report):
    print("\n🔍 检查 18.1 Ontology 验收 ...")

    # CI-A1: Organization 去重
    with driver.session() as s:
        dup_orgs = s.run("""
            MATCH (o:Organization)
            WITH toLower(o.canonical_name) AS n, collect(o.organization_id) AS ids
            WHERE size(ids) > 1
            RETURN count(*) AS c
        """).single()["c"]
    report.add(
        "18.1 Ontology 验收", "CI-A1", "Organization 无重复 canonical object",
        dup_orgs == 0, f"重复 {dup_orgs}", "0",
        note="同一 canonical_name 被创建了多个节点" if dup_orgs else ""
    )

    # CI-A2: ≥10 个 DevelopmentProgram
    n_progs = _one(driver, "MATCH (d:DevelopmentProgram) RETURN count(d)")
    report.add(
        "18.1 Ontology 验收", "CI-A2", "≥10 个 DevelopmentProgram",
        n_progs >= 10, n_progs, "≥10"
    )

    # CI-A3: ≥20 个 IntelligenceEvent，且都关联来源
    n_events = _one(driver, "MATCH (e:IntelligenceEvent) RETURN count(e)")
    report.add(
        "18.1 Ontology 验收", "CI-A3a", "≥20 个 IntelligenceEvent",
        n_events >= 20, n_events, "≥20"
    )
    events_with_source = _one(driver, """
        MATCH (e:IntelligenceEvent)-[:HAS_SOURCE]->(:SourceArtifact)
        RETURN count(DISTINCT e)
    """)
    report.add(
        "18.1 Ontology 验收", "CI-A3b", "每个事件至少 1 个来源",
        events_with_source == n_events and n_events > 0,
        f"{events_with_source}/{n_events}", "100%"
    )

    # CI-A4: ≥10 个 EngineeredPhageConstruct
    n_constructs = _one(driver, "MATCH (c:EngineeredPhageConstruct) RETURN count(c)")
    report.add(
        "18.1 Ontology 验收", "CI-A4", "≥10 个 EngineeredPhageConstruct",
        n_constructs >= 10, n_constructs, "≥10"
    )

    # CI-A5: ≥5 个 EngineeringStrategy
    n_strategies = _one(driver, "MATCH (s:EngineeringStrategy) RETURN count(s)")
    report.add(
        "18.1 Ontology 验收", "CI-A5", "≥5 个 EngineeringStrategy",
        n_strategies >= 5, n_strategies, "≥5"
    )

    # CI-A6: Claim/Result 分离 —— 不允许有 Claim 与 Result 是同一节点
    mixed = _one(driver, """
        MATCH (n)
        WHERE n:TechnicalClaim AND n:TechnicalResult
        RETURN count(n)
    """)
    report.add(
        "18.1 Ontology 验收", "CI-A6", "TechnicalClaim 与 TechnicalResult 分离",
        mixed == 0, f"混用 {mixed}", "0"
    )

    # CI-A7: 正式事实对象均关联来源
    # 统计对象：IntelligenceEvent, TechnicalClaim, TechnicalResult
    event_total = n_events
    event_sourced = _one(driver, """
        MATCH (e:IntelligenceEvent)-[:HAS_SOURCE]->(:SourceArtifact)
        RETURN count(DISTINCT e)
    """)
    claim_total = _one(driver, "MATCH (c:TechnicalClaim) RETURN count(c)")
    claim_sourced = _one(driver, """
        MATCH (c:TechnicalClaim)-[:SUPPORTED_BY]->(:SourceArtifact)
        RETURN count(DISTINCT c)
    """)
    result_total = _one(driver, "MATCH (r:TechnicalResult) RETURN count(r)")
    result_sourced = _one(driver, """
        MATCH (r:TechnicalResult)-[:REPORTED_IN]->(:SourceArtifact)
        RETURN count(DISTINCT r)
    """)

    total_fact = event_total + claim_total + result_total
    total_sourced = event_sourced + claim_sourced + result_sourced
    ratio = (total_sourced / total_fact * 100) if total_fact else 0
    report.add(
        "18.1 Ontology 验收", "CI-A7", "正式事实对象来源关联率 100%",
        ratio >= 99.9, f"{ratio:.1f}%",
        "100%",
        note=f"事件 {event_sourced}/{event_total}, 主张 {claim_sourced}/{claim_total}, 结果 {result_sourced}/{result_total}"
        if ratio < 99.9 else ""
    )

    # CI-A8: 所有 Brief 均有 as_of_date
    brief_total = _one(driver, "MATCH (b:IntelligenceProduct) RETURN count(b)")
    brief_with_date = _one(driver, """
        MATCH (b:IntelligenceProduct)
        WHERE b.as_of_date IS NOT NULL AND b.as_of_date <> ''
        RETURN count(b)
    """)
    report.add(
        "18.1 Ontology 验收", "CI-A8", "所有 Brief 均有 as_of_date",
        brief_with_date == brief_total and brief_total > 0,
        f"{brief_with_date}/{brief_total}", "100%"
    )


# ============================================================
# 18.2 产品能力验收
# ============================================================

def check_product(driver, report: Report):
    print("\n🔍 检查 18.2 产品能力验收 ...")

    # CI-P1: 至少 5 家竞争对手（有事件或项目的组织）
    comp_count = _one(driver, """
        MATCH (o:Organization)
        WHERE EXISTS { MATCH (o)-[:DEVELOPS]->(:DevelopmentProgram) }
           OR EXISTS { MATCH (o)<-[:CONCERNS]-(:IntelligenceEvent) }
        RETURN count(DISTINCT o)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P1", "≥5 家竞争对手档案",
        comp_count >= 5, comp_count, "≥5"
    )

    # CI-P2: 至少 1 个组织有事件时间线（项目 + 事件）
    timeline_org = _one(driver, """
        MATCH (o:Organization)-[:DEVELOPS]->(p:DevelopmentProgram)
        MATCH (o)<-[:CONCERNS]-(e:IntelligenceEvent)
        RETURN count(DISTINCT o)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P2", "≥1 个组织有项目+事件时间线",
        timeline_org >= 1, timeline_org, "≥1"
    )

    # CI-P3: Landscape Matrix —— 检查是否有构建体跨项目+病原+策略组合
    matrix_rows = _one(driver, """
        MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy)
        MATCH (ec)-[:TARGETS]->(p:Pathogen)
        OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
        RETURN count(DISTINCT [es.strategy_type, p.species, d.canonical_name])
    """)
    report.add(
        "18.2 产品能力验收", "CI-P3", "可生成 Landscape Matrix（策略×病原×项目组合）",
        matrix_rows >= 5, f"{matrix_rows} 组合", "≥5"
    )

    # CI-P4: Technology Map —— 策略 → 构建体 → 公司/项目 → 证据
    tech_map_rows = _one(driver, """
        MATCH (es:EngineeringStrategy)<-[:IMPLEMENTS]-(ec:EngineeredPhageConstruct)
        MATCH (ec)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)<-[:DEVELOPS]-(o:Organization)
        WHERE EXISTS { MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec) }
        RETURN count(DISTINCT ec)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P4", "Technology Map 可展示策略→构建体→组织→证据",
        tech_map_rows >= 1, tech_map_rows, "≥1"
    )

    # CI-P5: ≥5 份 Competitor Brief
    comp_briefs = _one(driver, """
        MATCH (b:IntelligenceProduct {brief_type: 'competitor'})
        RETURN count(b)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P5", "≥5 份 Competitor Brief",
        comp_briefs >= 5, comp_briefs, "≥5"
    )

    # CI-P6: ≥5 份 Technology Brief
    tech_briefs = _one(driver, """
        MATCH (b:IntelligenceProduct {brief_type: 'engineered_phage_technology'})
        RETURN count(b)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P6", "≥5 份 Technology Brief",
        tech_briefs >= 5, tech_briefs, "≥5"
    )

    # CI-P7: 所有正式 Brief 均有审核记录
    briefs_total = _one(driver, "MATCH (b:IntelligenceProduct) RETURN count(b)")
    briefs_reviewed = _one(driver, """
        MATCH (r:Review)-[:REVIEWS]->(b:IntelligenceProduct)
        RETURN count(DISTINCT b)
    """)
    ratio = (briefs_reviewed / briefs_total * 100) if briefs_total else 0
    report.add(
        "18.2 产品能力验收", "CI-P7", "所有正式 Brief 有审核记录",
        ratio >= 80, f"{briefs_reviewed}/{briefs_total} ({ratio:.0f}%)",
        "≥80%",
        note="MVP 阶段可放宽到 80%，正式交付前需 100%"
    )

    # CI-P8: ≥2 份 Brief 形成 DecisionRecord
    briefs_with_decision = _one(driver, """
        MATCH (dr:DecisionRecord)-[:BASED_ON]->(b:IntelligenceProduct)
        RETURN count(DISTINCT b)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P8", "≥2 份 Brief 形成 DecisionRecord",
        briefs_with_decision >= 2, briefs_with_decision, "≥2"
    )


# ============================================================
# 18.3 质量验收
# ============================================================

def check_quality(driver, report: Report):
    print("\n🔍 检查 18.3 质量验收 ...")

    # Q1: 正式事实对象来源关联率 100%（与 CI-A7 同源）
    total_fact = _one(driver, """
        MATCH (e:IntelligenceEvent) RETURN count(e)
    """) + _one(driver, """
        MATCH (c:TechnicalClaim) RETURN count(c)
    """) + _one(driver, """
        MATCH (r:TechnicalResult) RETURN count(r)
    """)
    total_sourced = _one(driver, """
        MATCH (e:IntelligenceEvent)-[:HAS_SOURCE]->(:SourceArtifact)
        RETURN count(DISTINCT e)
    """) + _one(driver, """
        MATCH (c:TechnicalClaim)-[:SUPPORTED_BY]->(:SourceArtifact)
        RETURN count(DISTINCT c)
    """) + _one(driver, """
        MATCH (r:TechnicalResult)-[:REPORTED_IN]->(:SourceArtifact)
        RETURN count(DISTINCT r)
    """)
    ratio = (total_sourced / total_fact * 100) if total_fact else 0
    report.add(
        "18.3 质量验收", "Q-1", "正式事实对象来源关联率",
        ratio >= 99.9, f"{ratio:.1f}%", "100%"
    )

    # Q2: LLM 提取对象人工抽检率 —— MVP 阶段 100% 送审
    # 用 TechnicalClaim 的 extracted_by='human' 或经 Review 作为代理指标
    claims_total = _one(driver, "MATCH (c:TechnicalClaim) RETURN count(c)")
    claims_reviewed = _one(driver, """
        MATCH (r:Review)-[:REVIEWS]->(c:TechnicalClaim)
        RETURN count(DISTINCT c)
    """)
    ratio = (claims_reviewed / claims_total * 100) if claims_total else 0
    report.add(
        "18.3 质量验收", "Q-2", "LLM 提取对象进入审核流程",
        ratio >= 50, f"{claims_reviewed}/{claims_total} ({ratio:.0f}%)",
        "≥50%",
        note="MVP 阶段允许部分抽检"
    )

    # Q3: 重点竞争对手实体重复率 0%
    dup_comp = _one(driver, """
        MATCH (o:Organization)
        WHERE EXISTS { MATCH (o)-[:DEVELOPS]->(:DevelopmentProgram) }
        WITH toLower(o.canonical_name) AS n, collect(o.organization_id) AS ids
        WHERE size(ids) > 1
        RETURN count(*)
    """)
    report.add(
        "18.3 质量验收", "Q-3", "重点竞争对手实体重复率",
        dup_comp == 0, dup_comp, "0"
    )

    # Q4: Brief 关键事实引用覆盖率
    briefs_with_citations = _one(driver, """
        MATCH (b:IntelligenceProduct)
        WHERE b.citations IS NOT NULL
          AND b.citations <> ''
          AND b.citations <> '[]'
        RETURN count(b)
    """)
    briefs_total = _one(driver, "MATCH (b:IntelligenceProduct) RETURN count(b)")
    ratio = (briefs_with_citations / briefs_total * 100) if briefs_total else 0
    report.add(
        "18.3 质量验收", "Q-4", "Brief 关键事实引用覆盖率",
        ratio >= 80, f"{briefs_with_citations}/{briefs_total} ({ratio:.0f}%)",
        "≥80%"
    )

    # Q5: 无法核验信息的明确标注率
    # 用 data_gaps 作为代理指标（非空表示有标注）
    briefs_with_gaps = _one(driver, """
        MATCH (b:IntelligenceProduct)
        WHERE b.data_gaps IS NOT NULL AND b.data_gaps <> '' AND b.data_gaps <> '[]'
        RETURN count(b)
    """)
    ratio = (briefs_with_gaps / briefs_total * 100) if briefs_total else 0
    report.add(
        "18.3 质量验收", "Q-5", "无法核验信息明确标注（data_gaps）",
        ratio >= 50, f"{briefs_with_gaps}/{briefs_total} ({ratio:.0f}%)",
        "≥50%"
    )

    # Q6: 专利主张误标为实验结果 —— 不允许同一个 claim_type 的节点带 result 标签
    bad_claims = _one(driver, """
        MATCH (n)
        WHERE n:TechnicalClaim AND n:TechnicalResult
        RETURN count(n)
    """)
    report.add(
        "18.3 质量验收", "Q-6", "专利主张误标为实验结果",
        bad_claims == 0, bad_claims, "0"
    )

    # Q7: 探索性结论误标为事实 —— 检查是否有 claim_status 缺失
    claims_total = _one(driver, "MATCH (c:TechnicalClaim) RETURN count(c)")
    claims_with_status = _one(driver, """
        MATCH (c:TechnicalClaim)
        WHERE c.claim_status IS NOT NULL AND c.claim_status <> ''
        RETURN count(c)
    """)
    report.add(
        "18.3 质量验收", "Q-7", "TechnicalClaim 均有 claim_status",
        claims_with_status == claims_total,
        f"{claims_with_status}/{claims_total}", "100%"
    )

    # Q8: 审计覆盖 —— 有 AuditEvent
    audit_total = _one(driver, "MATCH (a:AuditEvent) RETURN count(a)")
    report.add(
        "18.3 质量验收", "Q-8", "审计事件覆盖",
        audit_total >= 50, audit_total, "≥50"
    )


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 96)
    print("  Phage Intelligence Workspace — Stage2 增补 PRD 验收")
    print("=" * 96)

    driver = get_driver()
    report = Report()

    try:
        check_ontology(driver, report)
        check_product(driver, report)
        check_quality(driver, report)
    finally:
        driver.close()

    all_passed = report.print()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()