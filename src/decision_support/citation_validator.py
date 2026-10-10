# src/decision_support/citation_validator.py
"""
简报引用（citations）验证器。

职责：
    - 校验简报中的引用是否为空
    - 校验引用的 source_id 是否在图谱中存在
    - 检测重复的 source_id

支持对象：
    - IntelligenceProduct（brief_id）
    - DecisionBrief（brief_id）
"""
import json
from typing import Dict, List
from neo4j import Driver


def _load_citations(raw) -> List[Dict]:
    """
    把 citations 字段统一解析为列表。

    - None → []
    - str  → json.loads，失败时返回 []
    - list → 原样返回
    - 其他 → []
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return raw
    return []


def validate_brief_citations(driver: Driver, brief_id: str) -> Dict:
    """
    校验单个简报的引用。

    检查项：
        - total: 引用总数
        - unique: 去重后的 source_id 数
        - missing_source_ids: 图谱中不存在的 source_id
        - duplicate_source_ids: 出现多次的 source_id
        - empty_citations: 引用列表是否为空
        - ok: 是否通过（非空 + 无缺失 + 无重复）

    Args:
        driver: Neo4j 驱动
        brief_id: 简报 ID（IntelligenceProduct 或 DecisionBrief）

    Returns:
        Dict: 校验结果

    Raises:
        ValueError: 简报不存在
    """
    with driver.session() as s:
        rec = s.run("""
            MATCH (b)
            WHERE (b:IntelligenceProduct AND b.brief_id = $bid)
               OR (b:DecisionBrief AND b.brief_id = $bid)
            RETURN b.brief_id AS brief_id, b.citations AS citations
            LIMIT 1
        """, bid=brief_id).single()

    if not rec:
        raise ValueError(f"Brief {brief_id} 不存在")

    citations = _load_citations(rec.get("citations"))
    source_ids = [c.get("source_id") for c in citations if c.get("source_id")]

    # 检测重复
    seen, duplicates = set(), set()
    for sid in source_ids:
        if sid in seen:
            duplicates.add(sid)
        seen.add(sid)

    # 检测缺失（在图谱中不存在）
    missing = []
    if seen:
        with driver.session() as s:
            rows = s.run("""
                UNWIND $sids AS sid
                OPTIONAL MATCH (sa:SourceArtifact {source_id: sid})
                RETURN sid, sa IS NOT NULL AS exists
            """, sids=list(seen))
            for r in rows:
                if not r["exists"]:
                    missing.append(r["sid"])

    return {
        "brief_id": brief_id,
        "total": len(citations),
        "unique": len(seen),
        "missing_source_ids": missing,
        "duplicate_source_ids": sorted(duplicates),
        "empty_citations": len(citations) == 0,
        "ok": len(citations) > 0 and not missing and not duplicates,
    }


def validate_all_approved_briefs(driver: Driver, limit: int = 100) -> List[Dict]:
    """
    批量校验所有已批准的 IntelligenceProduct 引用。
    """
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (b:IntelligenceProduct)
            WHERE b.review_status = 'approved'
            RETURN b.brief_id AS brief_id
            LIMIT $limit
        """, limit=limit))
    return [validate_brief_citations(driver, r["brief_id"]) for r in rows]