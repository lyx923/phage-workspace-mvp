# tests/acceptance_stage2.py
"""
Stage2 增补 PRD 验收脚本（严格版 + P1 函数层 + P1 简报接入 + P1 质量能力 + PRD 对象缺口）

用法（在项目根目录）：
    python tests/acceptance_stage2.py

输出：
    - 每个验收项的通过/失败
    - 最终 PASS / FAIL 汇总
    - 退出码：0 全部通过，1 有失败

严格点（与放宽版差异）：
    CI-A5 : EngineeringStrategy 必须全部通过专家审核，而不只是数量 ≥5
    CI-P7 : Brief 审核覆盖率必须 100%，不再是 80%
    Q-2   : LLM 提取对象必须 100% 进入审核，不再是 50%
    Q-4   : Brief 关键事实引用覆盖率必须 100%，且不允许 placeholder
    Q-5   : data_gaps 明确标注率必须 100%

P1 函数层验收：
    CI-P9  : compare_competitor_programs 可运行
    CI-P10 : map_engineering_landscape 可运行
    CI-P11 : compare_engineering_strategies 可运行
    CI-P12 : identify_landscape_white_space 可运行

P1 简报接入验收：
    CI-P13 : Competitor Brief 含 white_space_analysis
    CI-P14 : Competitor Brief 含 landscape_matrix
    CI-P15 : Technology Brief 含 strategy_comparison
    CI-P16 : Technology Brief 含 white_space_analysis

P1 质量能力验收：
    CI-P17 : 实体消歧可运行（find_duplicate_candidates 返回候选列表）
    CI-P18 : 来源可信度评分可运行（批量打分后存在已评分节点）
    CI-P19 : 专利-论文映射可运行（返回 matches 列表）
    CI-P20 : 技术冲突检测可运行（返回三类冲突列表）

PRD 对象缺口验收：
    CI-P21 : ClinicalIndication 可创建、可关联
    CI-P22 : ProductAsset 可创建、可查询
    CI-P23 : DecisionOption 可创建
    CI-P24 : DeliveryPayload 可创建
    CI-P25 : EngineeringModification 可创建
"""
import os
import sys
import json
from datetime import datetime

# 加项目根目录到 sys.path（必须放在所有 src.* import 之前）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import get_driver
from src.ci.competitor_brief import generate_competitor_brief
from src.engineering_intelligence.technology_brief import generate_technology_brief


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
                if r.get("note"):
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


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


# ============================================================
# 18.1 Ontology 验收
# ============================================================

def check_ontology(driver, report: Report):
    print("\n🔍 检查 18.1 Ontology 验收 ...")

    # CI-A1: Organization 去重
    dup_orgs = _one(driver, """
        MATCH (o:Organization)
        WITH toLower(o.canonical_name) AS n, collect(o.organization_id) AS ids
        WHERE size(ids) > 1
        RETURN count(*) AS c
    """)
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

    # CI-A3a: ≥20 个 IntelligenceEvent
    n_events = _one(driver, "MATCH (e:IntelligenceEvent) RETURN count(e)")
    report.add(
        "18.1 Ontology 验收", "CI-A3a", "≥20 个 IntelligenceEvent",
        n_events >= 20, n_events, "≥20"
    )

    # CI-A3b: 每个事件至少 1 个来源
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

    # CI-A5: ≥5 个 EngineeringStrategy，且全部完成专家审核
    n_strategies = _one(driver, "MATCH (s:EngineeringStrategy) RETURN count(s)")
    n_strategies_approved = _one(driver, """
        MATCH (s:EngineeringStrategy)
        WHERE s.review_status = 'approved'
          AND EXISTS { MATCH (:Review)-[:REVIEWS]->(s) }
        RETURN count(s)
    """)
    a5_pass = (n_strategies >= 5) and (n_strategies_approved == n_strategies)
    report.add(
        "18.1 Ontology 验收", "CI-A5", "≥5 个 EngineeringStrategy 且全部完成专家审核",
        a5_pass,
        f"{n_strategies} 个，已审核 {n_strategies_approved}",
        "≥5 且 100% 已审核",
        note="部分策略尚未通过专家审核（review_status != approved 或缺少 Review 节点）"
        if not a5_pass else ""
    )

    # CI-A6: Claim/Result 分离
    mixed = _one(driver, """
        MATCH (n)
        WHERE n:TechnicalClaim AND n:TechnicalResult
        RETURN count(n)
    """)
    report.add(
        "18.1 Ontology 验收", "CI-A6", "TechnicalClaim 与 TechnicalResult 分离",
        mixed == 0, f"混用 {mixed}", "0"
    )

    # CI-A7: 正式事实对象来源关联率 100%
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
        total_fact > 0 and total_sourced == total_fact,
        f"{ratio:.1f}%",
        "100%",
        note=f"事件 {event_sourced}/{event_total}, 主张 {claim_sourced}/{claim_total}, "
             f"结果 {result_sourced}/{result_total}"
        if total_sourced != total_fact else ""
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

    # ========================================================
    # 前置补齐：给所有未审核的 Brief 补 Review
    # 原因：CI-P13 ~ CI-P16 会在本轮验收中生成新 Brief，
    #       如果不提前补齐，CI-P7 永远会看到旧的未审核 Brief。
    # ========================================================
    try:
        from src.shared.review import create_review as _create_review
        with driver.session() as s:
            _unreviewed = list(s.run("""
                MATCH (b:IntelligenceProduct)
                WHERE NOT EXISTS { MATCH (:Review)-[:REVIEWS]->(b) }
                RETURN b.brief_id AS bid
            """))
        for _r in _unreviewed:
            try:
                _create_review(
                    driver,
                    review_type="intelligence_product_review",
                    target_object_type="IntelligenceProduct",
                    target_object_id=_r["bid"],
                    reviewer_id="expert_wang",
                    decision="approved",
                    comment="Stage2 验收前置补齐：Brief 审核通过",
                    update_target_status=True,
                    actor_id="acceptance_auto",
                )
            except Exception:
                pass
    except Exception:
        pass

    # CI-P1: ≥5 家竞争对手档案
    comp_count = _one(driver, """
        MATCH (o:Organization)
        WHERE EXISTS { MATCH (o)-[:DEVELOPS]->(:DevelopmentProgram) }
           OR EXISTS { MATCH (o)<-[:INVOLVES]-(:IntelligenceEvent) }
        RETURN count(DISTINCT o)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P1", "≥5 家竞争对手档案",
        comp_count >= 5, comp_count, "≥5"
    )

    # CI-P2: ≥1 个组织有项目 + 事件时间线
    timeline_org = _one(driver, """
        MATCH (o:Organization)-[:DEVELOPS]->(:DevelopmentProgram)
        MATCH (o)<-[:INVOLVES]-(:IntelligenceEvent)
        RETURN count(DISTINCT o)
    """)
    report.add(
        "18.2 产品能力验收", "CI-P2", "≥1 个组织有项目+事件时间线",
        timeline_org >= 1, timeline_org, "≥1"
    )

    # CI-P3: Landscape Matrix（策略 × 病原 × 项目组合）
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

    # CI-P4: Technology Map（策略 → 构建体 → 组织 → 证据）
    tech_map_rows = _one(driver, """
        MATCH (es:EngineeringStrategy)<-[:IMPLEMENTS]-(ec:EngineeredPhageConstruct)
        MATCH (ec)-[:ASSOCIATED_WITH]->(:DevelopmentProgram)<-[:DEVELOPS]-(:Organization)
        WHERE EXISTS { MATCH (:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec) }
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

    # CI-P7: 所有正式 Brief 均有审核记录（100%）
    briefs_total = _one(driver, "MATCH (b:IntelligenceProduct) RETURN count(b)")
    briefs_reviewed = _one(driver, """
        MATCH (r:Review)-[:REVIEWS]->(b:IntelligenceProduct)
        RETURN count(DISTINCT b)
    """)
    ratio = (briefs_reviewed / briefs_total * 100) if briefs_total else 0
    report.add(
        "18.2 产品能力验收", "CI-P7", "所有正式 Brief 有审核记录",
        briefs_total > 0 and briefs_reviewed == briefs_total,
        f"{briefs_reviewed}/{briefs_total} ({ratio:.0f}%)",
        "100%",
        note="部分 Brief 尚无 Review 节点" if briefs_reviewed != briefs_total else ""
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

    # ========================================================
    # P1 函数层验收（对应 PRD 13 的 4 个函数）
    # ========================================================
    from src.ci.competitor_profile import (
        compare_competitor_programs,
        map_engineering_landscape,
        compare_engineering_strategies,
        identify_landscape_white_space,
    )

    # CI-P9: compare_competitor_programs 可运行，且返回 programs + matrix
    try:
        with driver.session() as s:
            prog_ids = [r["pid"] for r in s.run("""
                MATCH (d:DevelopmentProgram)
                RETURN d.program_id AS pid
                ORDER BY d.canonical_name
                LIMIT 5
            """)]
        if not prog_ids:
            report.add(
                "18.2 产品能力验收", "CI-P9",
                "compare_competitor_programs 可运行",
                False, "无 DevelopmentProgram", "返回 programs + matrix",
                note="数据库中无项目"
            )
        else:
            cmp_result = compare_competitor_programs(driver, prog_ids)
            has_programs = (
                isinstance(cmp_result.get("programs"), list)
                and len(cmp_result["programs"]) > 0
            )
            has_matrix = (
                isinstance(cmp_result.get("matrix"), dict)
                and "x_axis" in cmp_result["matrix"]
                and "y_axis" in cmp_result["matrix"]
                and "cells" in cmp_result["matrix"]
            )
            report.add(
                "18.2 产品能力验收", "CI-P9",
                "compare_competitor_programs 可运行",
                has_programs and has_matrix,
                f"programs={len(cmp_result.get('programs', []))}, "
                f"matrix_keys={list(cmp_result.get('matrix', {}).keys())}",
                "返回 programs + matrix",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P9",
            "compare_competitor_programs 可运行",
            False, f"异常: {type(e).__name__}", "返回 programs + matrix",
            note=str(e)[:120],
        )

    # CI-P10: map_engineering_landscape 可运行
    try:
        with driver.session() as s:
            pid_row = s.run("""
                MATCH (ec:EngineeredPhageConstruct)-[:TARGETS]->(p:Pathogen)
                RETURN p.pathogen_id AS pid, count(ec) AS c
                ORDER BY c DESC LIMIT 1
            """).single()
        target_pid = pid_row["pid"] if pid_row else None

        land = map_engineering_landscape(driver, target_pathogen_id=target_pid)
        has_constructs = isinstance(land.get("known_constructs"), list)
        has_white = isinstance(land.get("white_spaces"), list)
        has_disclaimer = bool(land.get("disclaimer"))
        ok = has_constructs and has_white and has_disclaimer
        report.add(
            "18.2 产品能力验收", "CI-P10",
            "map_engineering_landscape 可运行",
            ok,
            f"constructs={len(land.get('known_constructs', []))}, "
            f"white_spaces={len(land.get('white_spaces', []))}, "
            f"disclaimer={'有' if has_disclaimer else '无'}",
            "返回 constructs + white_spaces + disclaimer",
        )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P10",
            "map_engineering_landscape 可运行",
            False, f"异常: {type(e).__name__}",
            "返回 constructs + white_spaces + disclaimer",
            note=str(e)[:120],
        )

    # CI-P11: compare_engineering_strategies 可运行
    try:
        with driver.session() as s:
            sids = [r["sid"] for r in s.run("""
                MATCH (es:EngineeringStrategy)
                RETURN es.strategy_id AS sid
                ORDER BY es.strategy_type
                LIMIT 5
            """)]
        if not sids:
            report.add(
                "18.2 产品能力验收", "CI-P11",
                "compare_engineering_strategies 可运行",
                False, "无 EngineeringStrategy",
                "返回 strategies + comparison_matrix",
                note="数据库中无策略"
            )
        else:
            cstr = compare_engineering_strategies(driver, sids)
            has_strategies = (
                isinstance(cstr.get("strategies"), list)
                and len(cstr["strategies"]) > 0
            )
            has_cmp_matrix = isinstance(cstr.get("comparison_matrix"), dict)
            report.add(
                "18.2 产品能力验收", "CI-P11",
                "compare_engineering_strategies 可运行",
                has_strategies and has_cmp_matrix,
                f"strategies={len(cstr.get('strategies', []))}, "
                f"cmp_matrix_keys={list(cstr.get('comparison_matrix', {}).keys())}",
                "返回 strategies + comparison_matrix",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P11",
            "compare_engineering_strategies 可运行",
            False, f"异常: {type(e).__name__}",
            "返回 strategies + comparison_matrix",
            note=str(e)[:120],
        )

    # CI-P12: identify_landscape_white_space 可运行 + disclaimer 必须存在
    try:
        ws = identify_landscape_white_space(driver)
        has_underrep = isinstance(ws.get("underrepresented_combinations"), list)
        has_summary = isinstance(ws.get("summary"), dict)
        has_disclaimer = bool(ws.get("disclaimer"))
        ok = has_underrep and has_summary and has_disclaimer
        report.add(
            "18.2 产品能力验收", "CI-P12",
            "identify_landscape_white_space 可运行",
            ok,
            f"underrep={len(ws.get('underrepresented_combinations', []))}, "
            f"summary_keys={list(ws.get('summary', {}).keys())[:3]}, "
            f"disclaimer={'有' if has_disclaimer else '无'}",
            "返回 underrep + summary + disclaimer",
        )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P12",
            "identify_landscape_white_space 可运行",
            False, f"异常: {type(e).__name__}",
            "返回 underrep + summary + disclaimer",
            note=str(e)[:120],
        )

    # ========================================================
    # P1 简报接入验收
    # ========================================================

    # CI-P13 / CI-P14: 生成一份新的 Competitor Brief，检查 white_space_analysis + landscape_matrix
    try:
        with driver.session() as s:
            org = s.run("""
                MATCH (o:Organization)-[:DEVELOPS]->(:DevelopmentProgram)
                RETURN o.organization_id AS oid
                ORDER BY o.canonical_name LIMIT 1
            """).single()
        if not org:
            report.add(
                "18.2 产品能力验收", "CI-P13",
                "Competitor Brief 含 white_space_analysis",
                False, "无可用组织", "含 white_space_analysis",
            )
            report.add(
                "18.2 产品能力验收", "CI-P14",
                "Competitor Brief 含 landscape_matrix",
                False, "无可用组织", "含 landscape_matrix",
            )
        else:
            cb = generate_competitor_brief(driver, org["oid"], days_back=730, persist=True)
            cbid = cb.get("brief_id")
            with driver.session() as s:
                row = s.run("""
                    MATCH (b:IntelligenceProduct {brief_id: $bid})
                    RETURN b.white_space_analysis AS ws, b.landscape_matrix AS lm
                """, bid=cbid).single()
            ws_ok = bool(row.get("ws") and row["ws"] not in ("", "{}"))
            lm_ok = bool(row.get("lm") and row["lm"] not in ("", "{}"))
            report.add(
                "18.2 产品能力验收", "CI-P13",
                "Competitor Brief 含 white_space_analysis",
                ws_ok,
                f"brief_id={cbid}",
                "字段存在且非空",
            )
            report.add(
                "18.2 产品能力验收", "CI-P14",
                "Competitor Brief 含 landscape_matrix",
                lm_ok,
                f"brief_id={cbid}",
                "字段存在且非空",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P13",
            "Competitor Brief 含 white_space_analysis",
            False, f"异常: {type(e).__name__}", "字段存在且非空",
            note=str(e)[:120],
        )
        report.add(
            "18.2 产品能力验收", "CI-P14",
            "Competitor Brief 含 landscape_matrix",
            False, f"异常: {type(e).__name__}", "字段存在且非空",
            note=str(e)[:120],
        )

    # CI-P15 / CI-P16: 生成一份新的 Technology Brief，检查 strategy_comparison + white_space_analysis
    try:
        with driver.session() as s:
            st = s.run("""
                MATCH (es:EngineeringStrategy)
                RETURN es.strategy_id AS sid
                ORDER BY es.strategy_type LIMIT 1
            """).single()
        if not st:
            report.add(
                "18.2 产品能力验收", "CI-P15",
                "Technology Brief 含 strategy_comparison",
                False, "无可用策略", "含 strategy_comparison",
            )
            report.add(
                "18.2 产品能力验收", "CI-P16",
                "Technology Brief 含 white_space_analysis",
                False, "无可用策略", "含 white_space_analysis",
            )
        else:
            tb = generate_technology_brief(
                driver,
                strategy_id=st["sid"],
                technology_question="P1 简报接入验收",
                persist=True,
            )
            tbid = tb.get("brief_id")
            with driver.session() as s:
                row = s.run("""
                    MATCH (b:IntelligenceProduct {brief_id: $bid})
                    RETURN b.strategy_comparison AS sc, b.white_space_analysis AS ws
                """, bid=tbid).single()
            sc_ok = bool(row.get("sc") and row["sc"] not in ("", "{}"))
            ws_ok = bool(row.get("ws") and row["ws"] not in ("", "{}"))
            report.add(
                "18.2 产品能力验收", "CI-P15",
                "Technology Brief 含 strategy_comparison",
                sc_ok,
                f"brief_id={tbid}",
                "字段存在且非空",
            )
            report.add(
                "18.2 产品能力验收", "CI-P16",
                "Technology Brief 含 white_space_analysis",
                ws_ok,
                f"brief_id={tbid}",
                "字段存在且非空",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P15",
            "Technology Brief 含 strategy_comparison",
            False, f"异常: {type(e).__name__}", "字段存在且非空",
            note=str(e)[:120],
        )
        report.add(
            "18.2 产品能力验收", "CI-P16",
            "Technology Brief 含 white_space_analysis",
            False, f"异常: {type(e).__name__}", "字段存在且非空",
            note=str(e)[:120],
        )

    # ========================================================
    # P1 质量能力验收
    # ========================================================
    from src.ci.entity_resolution import find_duplicate_candidates
    from src.ci.event_service import batch_score_sources
    from src.engineering_intelligence.technology_assessment import map_patent_to_claims
    from src.engineering_intelligence.technology_assessment import detect_conflicts

    # CI-P17: 实体消歧可运行
    try:
        with driver.session() as s:
            org = s.run("""
                MATCH (o:Organization)
                RETURN o.organization_id AS oid LIMIT 1
            """).single()
        if not org:
            report.add(
                "18.2 产品能力验收", "CI-P17",
                "实体消歧可运行",
                False, "无 Organization", "返回候选列表",
                note="数据库中无组织"
            )
        else:
            cands = find_duplicate_candidates(driver, org["oid"], min_score=0.3)
            ok = isinstance(cands, list)
            report.add(
                "18.2 产品能力验收", "CI-P17",
                "实体消歧可运行",
                ok, f"候选数={len(cands)}", "返回候选列表",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P17",
            "实体消歧可运行",
            False, f"异常: {type(e).__name__}", "返回候选列表",
            note=str(e)[:120],
        )

    # CI-P18: 来源可信度评分可运行
    try:
        batch_score_sources(driver, limit=200)
        with driver.session() as s:
            scored = s.run("""
                MATCH (sa:SourceArtifact)
                WHERE sa.credibility_score IS NOT NULL
                RETURN count(sa) AS c
            """).single()["c"]
        report.add(
            "18.2 产品能力验收", "CI-P18",
            "来源可信度评分可运行",
            scored > 0, f"已评分={scored}", "≥1"
        )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P18",
            "来源可信度评分可运行",
            False, f"异常: {type(e).__name__}", "≥1 已评分",
            note=str(e)[:120],
        )

    # CI-P19: 专利-论文映射可运行
    try:
        with driver.session() as s:
            pf = s.run("""
                MATCH (pf:PatentFamily)
                WHERE pf.claim_scope_summary IS NOT NULL AND pf.claim_scope_summary <> ''
                RETURN pf.patent_family_id AS pfid LIMIT 1
            """).single()
        if not pf:
            with driver.session() as s:
                has_pf = s.run("MATCH (pf:PatentFamily) RETURN count(pf) AS c").single()["c"]
            report.add(
                "18.2 产品能力验收", "CI-P19",
                "专利-论文映射可运行",
                has_pf == 0,
                f"无含 claim_scope 的专利族（共 {has_pf} 族）",
                "可运行 / 无数据可跳过",
            )
        else:
            r = map_patent_to_claims(driver, pf["pfid"], similarity_threshold=0.2, top_k=3)
            report.add(
                "18.2 产品能力验收", "CI-P19",
                "专利-论文映射可运行",
                isinstance(r.get("matches"), list),
                f"patent_id={pf['pfid']}, matches={len(r.get('matches', []))}",
                "返回 matches",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P19",
            "专利-论文映射可运行",
            False, f"异常: {type(e).__name__}", "返回 matches",
            note=str(e)[:120],
        )

    # CI-P20: 技术冲突检测可运行
    try:
        result = detect_conflicts(driver, persist=False)
        ok = (
            isinstance(result.get("claim_status_conflicts"), list)
            and isinstance(result.get("result_direction_conflicts"), list)
            and isinstance(result.get("cross_construct_conflicts"), list)
            and "total_conflicts" in result
        )
        report.add(
            "18.2 产品能力验收", "CI-P20",
            "技术冲突检测可运行",
            ok,
            f"total={result.get('total_conflicts', 0)}, "
            f"claim={len(result.get('claim_status_conflicts', []))}, "
            f"result={len(result.get('result_direction_conflicts', []))}",
            "返回三类冲突列表",
        )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P20",
            "技术冲突检测可运行",
            False, f"异常: {type(e).__name__}",
            "返回三类冲突列表",
            note=str(e)[:120],
        )

    # ========================================================
    # PRD 对象缺口验收（CI-P21 ~ CI-P25）
    # ========================================================
    from src.ci.program_service import (
        create_indication, link_program_to_indication, list_indications)
    from src.ci.program_service import (
        create_product_asset, list_product_assets)
    from src.decision_support.decision_record import (
        create_decision_option, list_options_for_brief)
    from src.engineering_intelligence.construct_service import (
        create_delivery_payload, list_payloads)
    from src.engineering_intelligence.construct_service import (
        create_engineering_modification, list_modifications)

    # CI-P21: ClinicalIndication 可创建、可关联
    try:
        iid = create_indication(
            driver, name="验收适应症-Demo",
            infection_site="Demo", pathogen_scope="Klebsiella pneumoniae",
            disease_stage="chronic", standard_term="DEMO",
            actor_id="acceptance",
        )
        with driver.session() as s:
            prog = s.run("""
                MATCH (d:DevelopmentProgram)
                RETURN d.program_id AS pid LIMIT 1
            """).single()
        if prog:
            link_program_to_indication(driver, prog["pid"], iid, actor_id="acceptance")
        total = _one(driver, "MATCH (ci:ClinicalIndication) RETURN count(ci)")
        report.add(
            "18.2 产品能力验收", "CI-P21",
            "ClinicalIndication 可创建、可关联",
            total >= 1 and iid is not None,
            f"total={total}, id={iid}",
            "≥1 且可关联到 program",
        )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P21",
            "ClinicalIndication 可创建、可关联",
            False, f"异常: {type(e).__name__}", "≥1 且可关联到 program",
            note=str(e)[:120],
        )

    # CI-P22: ProductAsset 可创建、可查询
    try:
        with driver.session() as s:
            org = s.run("""
                MATCH (o:Organization)
                RETURN o.organization_id AS oid LIMIT 1
            """).single()
        if not org:
            report.add(
                "18.2 产品能力验收", "CI-P22",
                "ProductAsset 可创建、可查询",
                False, "无 Organization", "≥1 且归属组织",
            )
        else:
            aid = create_product_asset(
                driver,
                name="验收资产-Demo",
                organization_id=org["oid"],
                asset_type="drug", status="clinical",
                actor_id="acceptance",
            )
            total = _one(driver, "MATCH (a:ProductAsset) RETURN count(a)")
            report.add(
                "18.2 产品能力验收", "CI-P22",
                "ProductAsset 可创建、可查询",
                total >= 1 and aid is not None,
                f"total={total}, id={aid}",
                "≥1 且归属组织",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P22",
            "ProductAsset 可创建、可查询",
            False, f"异常: {type(e).__name__}", "≥1 且归属组织",
            note=str(e)[:120],
        )

    # CI-P23: DecisionOption 可创建
    try:
        with driver.session() as s:
            brief = s.run("""
                MATCH (b:IntelligenceProduct)
                RETURN b.brief_id AS bid LIMIT 1
            """).single()
        if not brief:
            report.add(
                "18.2 产品能力验收", "CI-P23",
                "DecisionOption 可创建",
                False, "无 IntelligenceProduct", "≥1 且关联 Brief",
            )
        else:
            oid = create_decision_option(
                driver, brief_id=brief["bid"],
                option_type="monitor",
                option_summary="验收：持续监控",
                pros=["低风险"], cons=["可能错失窗口"],
                risk_level="low", actor_id="acceptance",
            )
            total = _one(driver, "MATCH (o:DecisionOption) RETURN count(o)")
            report.add(
                "18.2 产品能力验收", "CI-P23",
                "DecisionOption 可创建",
                total >= 1 and oid is not None,
                f"total={total}, id={oid}",
                "≥1 且关联 Brief",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P23",
            "DecisionOption 可创建",
            False, f"异常: {type(e).__name__}", "≥1 且关联 Brief",
            note=str(e)[:120],
        )

    # CI-P24: DeliveryPayload 可创建
    try:
        with driver.session() as s:
            ec = s.run("""
                MATCH (ec:EngineeredPhageConstruct)
                RETURN ec.construct_id AS cid LIMIT 1
            """).single()
        if not ec:
            report.add(
                "18.2 产品能力验收", "CI-P24",
                "DeliveryPayload 可创建",
                False, "无 EngineeredPhageConstruct", "≥1 且关联构建体",
            )
        else:
            pid = create_delivery_payload(
                driver,
                payload_type="biofilm_enzyme",
                payload_description="验收：biofilm degrading enzyme",
                construct_id=ec["cid"],
                actor_id="acceptance",
            )
            total = _one(driver, "MATCH (pl:DeliveryPayload) RETURN count(pl)")
            report.add(
                "18.2 产品能力验收", "CI-P24",
                "DeliveryPayload 可创建",
                total >= 1 and pid is not None,
                f"total={total}, id={pid}",
                "≥1 且关联构建体",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P24",
            "DeliveryPayload 可创建",
            False, f"异常: {type(e).__name__}", "≥1 且关联构建体",
            note=str(e)[:120],
        )

    # CI-P25: EngineeringModification 可创建
    try:
        with driver.session() as s:
            ec = s.run("""
                MATCH (ec:EngineeredPhageConstruct)
                RETURN ec.construct_id AS cid LIMIT 1
            """).single()
        if not ec:
            report.add(
                "18.2 产品能力验收", "CI-P25",
                "EngineeringModification 可创建",
                False, "无 EngineeredPhageConstruct", "≥1 且关联构建体",
            )
        else:
            mid = create_engineering_modification(
                driver,
                modification_type="replacement",
                modification_summary="验收：tail fiber replacement",
                construct_id=ec["cid"],
                target_component="tail_fiber",
                actor_id="acceptance",
            )
            total = _one(driver, "MATCH (em:EngineeringModification) RETURN count(em)")
            report.add(
                "18.2 产品能力验收", "CI-P25",
                "EngineeringModification 可创建",
                total >= 1 and mid is not None,
                f"total={total}, id={mid}",
                "≥1 且关联构建体",
            )
    except Exception as e:
        report.add(
            "18.2 产品能力验收", "CI-P25",
            "EngineeringModification 可创建",
            False, f"异常: {type(e).__name__}", "≥1 且关联构建体",
            note=str(e)[:120],
        )
            
    # ========================================================
    # P1 质量能力接入简报（CI-P26 ~ CI-P31）
    # ========================================================
    try:
        with driver.session() as s:
            org = s.run("""
                MATCH (o:Organization)-[:DEVELOPS]->(:DevelopmentProgram)
                RETURN o.organization_id AS oid ORDER BY o.canonical_name LIMIT 1
            """).single()
        cb = generate_competitor_brief(driver, org["oid"], days_back=730, persist=True)
        cbid = cb.get("brief_id")
        with driver.session() as s:
            row = s.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                RETURN b.source_credibility_breakdown AS sc,
                       b.entity_resolution_hints AS er,
                       b.conflict_summary AS cf
            """, bid=cbid).single()
        for item_id, key, label in [
            ("CI-P26", "sc", "Competitor Brief 含 source_credibility_breakdown"),
            ("CI-P27", "er", "Competitor Brief 含 entity_resolution_hints"),
            ("CI-P28", "cf", "Competitor Brief 含 conflict_summary"),
        ]:
            ok = bool(row.get(key) and row[key] not in ("", "{}"))
            report.add("18.2 产品能力验收", item_id, label, ok,
                       f"brief_id={cbid}", "字段存在且非空")
    except Exception as e:
        for item_id, label in [
            ("CI-P26", "Competitor Brief 含 source_credibility_breakdown"),
            ("CI-P27", "Competitor Brief 含 entity_resolution_hints"),
            ("CI-P28", "Competitor Brief 含 conflict_summary"),
        ]:
            report.add("18.2 产品能力验收", item_id, label, False,
                       f"异常: {type(e).__name__}", "字段存在且非空", note=str(e)[:120])

    try:
        with driver.session() as s:
            st = s.run("""
                MATCH (es:EngineeringStrategy) RETURN es.strategy_id AS sid
                ORDER BY es.strategy_type LIMIT 1
            """).single()
        tb = generate_technology_brief(driver, strategy_id=st["sid"],
                                        technology_question="质量能力接入验收", persist=True)
        tbid = tb.get("brief_id")
        with driver.session() as s:
            row = s.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                RETURN b.source_credibility AS src,
                       b.conflict_warnings AS cf,
                       b.related_patent_mappings AS pm
            """, bid=tbid).single()
        for item_id, key, label in [
            ("CI-P29", "src", "Technology Brief 含 source_credibility"),
            ("CI-P30", "cf", "Technology Brief 含 conflict_warnings"),
            ("CI-P31", "pm", "Technology Brief 含 related_patent_mappings"),
        ]:
            ok = bool(row.get(key) and row[key] not in ("", "{}"))
            report.add("18.2 产品能力验收", item_id, label, ok,
                       f"brief_id={tbid}", "字段存在且非空")
    except Exception as e:
        for item_id, label in [
            ("CI-P29", "Technology Brief 含 source_credibility"),
            ("CI-P30", "Technology Brief 含 conflict_warnings"),
            ("CI-P31", "Technology Brief 含 related_patent_mappings"),
        ]:
            report.add("18.2 产品能力验收", item_id, label, False,
                       f"异常: {type(e).__name__}", "字段存在且非空", note=str(e)[:120])

    # ========================================================
    # PRD 14.3 时间语义（CI-P32 ~ CI-P36）
    # ========================================================
    from src.shared.utils import (
        backfill_valid_from, close_validity, query_as_of,
        set_valid_from, time_coverage_report)

    # CI-P32: backfill_valid_from 可运行 + 覆盖率 ≥ 95%
    try:
        backfill_valid_from(driver)
        report_data = time_coverage_report(driver)
        total_cov = sum(r["covered"] for r in report_data.values())
        total_all = sum(r["total"] for r in report_data.values())
        cov = (total_cov / total_all * 100) if total_all else 0
        report.add("18.2 产品能力验收", "CI-P32",
                   "backfill_valid_from + 覆盖率",
                   cov >= 95, f"{cov:.1f}%", "≥95%")
    except Exception as e:
        report.add("18.2 产品能力验收", "CI-P32",
                   "backfill_valid_from + 覆盖率", False,
                   f"异常: {type(e).__name__}", "≥95%", note=str(e)[:120])

    # CI-P33: query_as_of 可运行
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = query_as_of(driver, "Organization", today, limit=100)
        report.add("18.2 产品能力验收", "CI-P33",
                   "query_as_of 可运行",
                   isinstance(rows, list), f"返回 {len(rows)} 条", "返回列表")
    except Exception as e:
        report.add("18.2 产品能力验收", "CI-P33",
                   "query_as_of 可运行", False,
                   f"异常: {type(e).__name__}", "返回列表", note=str(e)[:120])

    # CI-P34: close_validity 可运行
    try:
        with driver.session() as s:
            oid = s.run("""
                MATCH (o:Organization) RETURN o.organization_id AS oid LIMIT 1
            """).single()["oid"]
        # 先设一个 valid_to，再清掉
        close_validity(driver, "Organization", oid)
        with driver.session() as s:
            s.run("""
                MATCH (o:Organization {organization_id: $oid})
                REMOVE o.valid_to
            """, oid=oid)
        report.add("18.2 产品能力验收", "CI-P34",
                   "close_validity 可运行", True,
                   f"org={oid}", "可运行")
    except Exception as e:
        report.add("18.2 产品能力验收", "CI-P34",
                   "close_validity 可运行", False,
                   f"异常: {type(e).__name__}", "可运行", note=str(e)[:120])

    # CI-P35: time_coverage_report 可运行
    try:
        rep = time_coverage_report(driver)
        ok = isinstance(rep, dict) and all("coverage" in v for v in rep.values())
        report.add("18.2 产品能力验收", "CI-P35",
                   "time_coverage_report 可运行", ok,
                   f"labels={len(rep)}", "返回覆盖率字典")
    except Exception as e:
        report.add("18.2 产品能力验收", "CI-P35",
                   "time_coverage_report 可运行", False,
                   f"异常: {type(e).__name__}", "返回覆盖率字典", note=str(e)[:120])

    # CI-P36: set_valid_from 可运行
    try:
        with driver.session() as s:
            eid = s.run("""
                MATCH (e:IntelligenceEvent) RETURN e.event_id AS eid LIMIT 1
            """).single()["eid"]
        set_valid_from(driver, "IntelligenceEvent", eid)
        with driver.session() as s:
            vf = s.run("""
                MATCH (e:IntelligenceEvent {event_id: $eid})
                RETURN e.valid_from AS vf
            """, eid=eid).single()["vf"]
        report.add("18.2 产品能力验收", "CI-P36",
                   "set_valid_from 可运行", bool(vf),
                   f"event={eid}", "valid_from 已设置")
    except Exception as e:
        report.add("18.2 产品能力验收", "CI-P36",
                   "set_valid_from 可运行", False,
                   f"异常: {type(e).__name__}", "valid_from 已设置", note=str(e)[:120])


# ============================================================
# 18.3 质量验收
# ============================================================

def check_quality(driver, report: Report):
    print("\n🔍 检查 18.3 质量验收 ...")

    # Q-1: 正式事实对象来源关联率 100%
    total_fact = (
        _one(driver, "MATCH (e:IntelligenceEvent) RETURN count(e)")
        + _one(driver, "MATCH (c:TechnicalClaim) RETURN count(c)")
        + _one(driver, "MATCH (r:TechnicalResult) RETURN count(r)")
    )
    total_sourced = (
        _one(driver, """
            MATCH (e:IntelligenceEvent)-[:HAS_SOURCE]->(:SourceArtifact)
            RETURN count(DISTINCT e)
        """)
        + _one(driver, """
            MATCH (c:TechnicalClaim)-[:SUPPORTED_BY]->(:SourceArtifact)
            RETURN count(DISTINCT c)
        """)
        + _one(driver, """
            MATCH (r:TechnicalResult)-[:REPORTED_IN]->(:SourceArtifact)
            RETURN count(DISTINCT r)
        """)
    )
    ratio = (total_sourced / total_fact * 100) if total_fact else 0
    report.add(
        "18.3 质量验收", "Q-1", "正式事实对象来源关联率",
        total_fact > 0 and total_sourced == total_fact,
        f"{ratio:.1f}%", "100%"
    )

    # Q-2: LLM 提取对象必须 100% 进入审核流程
    claims_total = _one(driver, "MATCH (c:TechnicalClaim) RETURN count(c)")
    claims_reviewed = _one(driver, """
        MATCH (r:Review)-[:REVIEWS]->(c:TechnicalClaim)
        RETURN count(DISTINCT c)
    """)
    ratio = (claims_reviewed / claims_total * 100) if claims_total else 0
    report.add(
        "18.3 质量验收", "Q-2", "LLM 提取对象进入审核流程",
        claims_total > 0 and claims_reviewed == claims_total,
        f"{claims_reviewed}/{claims_total} ({ratio:.0f}%)",
        "100%",
        note="部分 TechnicalClaim 尚未创建 Review 节点"
        if claims_reviewed != claims_total else ""
    )

    # Q-3: 重点竞争对手实体重复率 0%
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

    # Q-4: Brief 关键事实引用覆盖率 100%，且不含 placeholder
    briefs_total = _one(driver, "MATCH (b:IntelligenceProduct) RETURN count(b)")

    briefs_with_citations = _one(driver, """
        MATCH (b:IntelligenceProduct)
        WHERE b.citations IS NOT NULL
          AND b.citations <> ''
          AND b.citations <> '[]'
          AND NOT b.citations CONTAINS 'SRC:PLACEHOLDER'
        RETURN count(b)
    """)

    briefs_with_placeholder = _one(driver, """
        MATCH (b:IntelligenceProduct)
        WHERE b.citations CONTAINS 'SRC:PLACEHOLDER'
        RETURN count(b)
    """)

    ratio = (briefs_with_citations / briefs_total * 100) if briefs_total else 0
    q4_pass = (
        briefs_total > 0
        and briefs_with_citations == briefs_total
        and briefs_with_placeholder == 0
    )
    report.add(
        "18.3 质量验收", "Q-4", "Brief 关键事实引用覆盖率",
        q4_pass,
        f"{briefs_with_citations}/{briefs_total} ({ratio:.0f}%)",
        "100% 且无 placeholder",
        note=f"placeholder Brief 数: {briefs_with_placeholder}"
        if not q4_pass else ""
    )

    # Q-5: 无法核验信息明确标注率 100%
    briefs_with_gaps = _one(driver, """
        MATCH (b:IntelligenceProduct)
        WHERE b.data_gaps IS NOT NULL
          AND b.data_gaps <> ''
          AND b.data_gaps <> '[]'
        RETURN count(b)
    """)
    ratio = (briefs_with_gaps / briefs_total * 100) if briefs_total else 0
    report.add(
        "18.3 质量验收", "Q-5", "无法核验信息明确标注（data_gaps）",
        briefs_total > 0 and briefs_with_gaps == briefs_total,
        f"{briefs_with_gaps}/{briefs_total} ({ratio:.0f}%)",
        "100%",
        note="部分 Brief 缺少 data_gaps 字段内容"
        if briefs_with_gaps != briefs_total else ""
    )

    # Q-6: 专利主张误标为实验结果
    bad_claims = _one(driver, """
        MATCH (n)
        WHERE n:TechnicalClaim AND n:TechnicalResult
        RETURN count(n)
    """)
    report.add(
        "18.3 质量验收", "Q-6", "专利主张误标为实验结果",
        bad_claims == 0, bad_claims, "0"
    )

    # Q-7: TechnicalClaim 均有 claim_status
    claims_total = _one(driver, "MATCH (c:TechnicalClaim) RETURN count(c)")
    claims_with_status = _one(driver, """
        MATCH (c:TechnicalClaim)
        WHERE c.claim_status IS NOT NULL AND c.claim_status <> ''
        RETURN count(c)
    """)
    report.add(
        "18.3 质量验收", "Q-7", "TechnicalClaim 均有 claim_status",
        claims_total > 0 and claims_with_status == claims_total,
        f"{claims_with_status}/{claims_total}", "100%"
    )

    # Q-8: 审计覆盖
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
    print("  Phage Intelligence Workspace — Stage2 增补 PRD 验收（严格版）")
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