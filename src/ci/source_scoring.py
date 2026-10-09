# src/ci/source_scoring.py
"""
MCI-14 来源可信度评分

评分模型（0-100）：
- 基础分（按 credibility_tier / source_type）
- URL 存在性加分
- published_date 存在性加分
- 审核状态加分
- 时间新鲜度惩罚（可选）
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


BASE_TIER_SCORE = {
    "primary": 80,
    "secondary": 55,
    "tertiary": 35,
    "unknown": 20,
}

SOURCE_TYPE_BONUS = {
    "regulatory_filing": 10,
    "clinical_trial_registry": 8,
    "peer_reviewed_paper": 10,
    "literature": 8,
    "patent": 6,
    "press_release": 2,
    "url_scrape": 0,
    "news": 0,
    "user_input": -5,
    "monitor_auto": -3,
}


def _score_one(sa: Dict) -> Dict:
    """
    对单个 SourceArtifact 计算评分。
    """
    tier = (sa.get("credibility_tier") or "unknown").lower()
    stype = (sa.get("source_type") or "unknown").lower()

    score = BASE_TIER_SCORE.get(tier, 20)
    reasons = [f"tier={tier} 基础分 {score}"]

    bonus_type = SOURCE_TYPE_BONUS.get(stype, 0)
    if bonus_type != 0:
        score += bonus_type
        reasons.append(f"source_type={stype} 加分 {bonus_type:+d}")

    if sa.get("url"):
        score += 5
        reasons.append("存在 url +5")

    if sa.get("published_date") and sa["published_date"] not in ("", "unknown"):
        score += 5
        reasons.append("存在 published_date +5")

    review_status = (sa.get("review_status") or "").lower()
    if review_status == "approved":
        score += 5
        reasons.append("review_status=approved +5")
    elif review_status == "disputed":
        score -= 10
        reasons.append("review_status=disputed -10")

    score = max(0, min(100, score))
    return {
        "score": score,
        "tier": tier,
        "source_type": stype,
        "reasons": reasons,
    }


def score_source_artifact(
    driver: Driver,
    source_id: str,
    actor_id: str = "source_scoring",
) -> Dict:
    """
    对单个 SourceArtifact 打分，并把结果写回节点属性 credibility_score。
    """
    with driver.session() as s:
        row = s.run("""
            MATCH (sa:SourceArtifact {source_id: $sid})
            RETURN sa.source_id AS source_id,
                   sa.source_type AS source_type,
                   sa.credibility_tier AS credibility_tier,
                   sa.url AS url,
                   sa.published_date AS published_date,
                   sa.review_status AS review_status
        """, sid=source_id).single()
        if not row:
            raise ValueError(f"SourceArtifact {source_id} 不存在")

        result = _score_one(dict(row))

        s.run("""
            MATCH (sa:SourceArtifact {source_id: $sid})
            SET sa.credibility_score = $score,
                sa.credibility_scored_at = datetime(),
                sa.updated_at = datetime()
        """, sid=source_id, score=result["score"])

    write_audit_event(
        driver,
        action_type="UPDATE",
        object_type="SourceArtifact",
        object_id=source_id,
        actor_id=actor_id,
        delta={"credibility_score": result["score"]},
        reason=f"来源可信度评分: {result['score']}（{'; '.join(result['reasons'][:3])}）",
    )
    result["source_id"] = source_id
    return result


def batch_score_sources(
    driver: Driver,
    limit: int = 500,
    actor_id: str = "source_scoring",
) -> Dict:
    """
    批量给所有未评分的 SourceArtifact 打分。
    """
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (sa:SourceArtifact)
            WHERE sa.credibility_score IS NULL
            RETURN sa.source_id AS sid
            LIMIT $limit
        """, limit=limit))

    scored = 0
    errors = []
    for r in rows:
        try:
            score_source_artifact(driver, r["sid"], actor_id=actor_id)
            scored += 1
        except Exception as e:
            errors.append(f"{r['sid']}: {e}")

    return {
        "total_candidates": len(rows),
        "scored": scored,
        "errors": errors[:10],
    }


def get_source_score(driver: Driver, source_id: str) -> Optional[Dict]:
    """读取已打分的结果（不重新计算）"""
    with driver.session() as s:
        row = s.run("""
            MATCH (sa:SourceArtifact {source_id: $sid})
            RETURN sa.source_id AS source_id,
                   sa.credibility_score AS credibility_score,
                   sa.credibility_tier AS credibility_tier,
                   sa.source_type AS source_type,
                   sa.credibility_scored_at AS scored_at
        """, sid=source_id).single()
    return dict(row) if row else None