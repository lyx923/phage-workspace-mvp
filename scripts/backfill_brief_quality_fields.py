# scripts/backfill_brief_quality_fields.py
"""
给历史 Brief 补质量能力字段（source_credibility / entity_resolution / conflict / patent_mappings）。

用途：
    用旧版 competitor_brief.py / technology_brief.py 生成的 Brief 没有质量能力字段。
    本脚本遍历所有缺字段的 Brief，调用对应的 build 函数补齐。

用法：
    python scripts/backfill_brief_quality_fields.py
"""
import os
import sys
import json
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import get_driver


def _has(v):
    return bool(v and v not in ("", "{}", "[]"))


def backfill_competitor_briefs(driver):
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


def backfill_technology_briefs(driver):
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
            # 若没有 construct，用任意一个 strategy 的专利
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


def main():
    print("=" * 80)
    print(f"  Brief 质量能力字段回填  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    driver = get_driver()
    try:
        print("\n[1/2] Competitor Briefs ...")
        n1 = backfill_competitor_briefs(driver)
        print(f"  完成：{n1} 份")

        print("\n[2/2] Technology Briefs ...")
        n2 = backfill_technology_briefs(driver)
        print(f"  完成：{n2} 份")
    finally:
        driver.close()

    print(f"\n总计回填 {n1 + n2} 份 Brief")


if __name__ == "__main__":
    main()