# src/engineering_intelligence/ip_mapping_service.py
"""
EPI-11 专利-论文映射

基于文本相似度，把 PatentFamily 与 TechnicalClaim 建立 MAPS_TO 关系。

边界：
- 只做文本相似度匹配，不做侵权/自由实施判断
- 相似度低于阈值的映射需要人工确认
- 不自动把专利权利要求等同为实验验证
"""
from __future__ import annotations

import re
import uuid
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


DEFAULT_SIMILARITY_THRESHOLD = 0.30


def _token_set(s: str) -> set:
    if not s:
        return set()
    return set(re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", s.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def map_patent_to_claims(
    driver: Driver,
    patent_family_id: str,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    top_k: int = 5,
    actor_id: str = "ip_mapping",
    persist: bool = True,
) -> Dict:
    """
    对指定 PatentFamily，找出相似度最高的 TechnicalClaim 并建立 MAPS_TO 关系。

    返回：
        {
          "patent_family_id": ...,
          "claim_scope_summary": ...,
          "matches": [
            {"claim_id": ..., "claim_text": ..., "similarity": 0.42, "already_mapped": False}
          ],
          "created_relations": [...]
        }
    """
    with driver.session() as s:
        pf = s.run("""
            MATCH (pf:PatentFamily {patent_family_id: $pfid})
            RETURN pf.patent_family_id AS pfid,
                   pf.title AS title,
                   pf.claim_scope_summary AS summary
        """, pfid=patent_family_id).single()
        if not pf:
            raise ValueError(f"PatentFamily {patent_family_id} 不存在")

        claims = list(s.run("""
            MATCH (tc:TechnicalClaim)
            WHERE tc.claim_text IS NOT NULL AND tc.claim_text <> ''
            RETURN tc.claim_id AS cid, tc.claim_text AS text,
                   tc.claim_type AS ctype
        """))

    text = (pf["summary"] or "") + " " + (pf["title"] or "")
    pf_tokens = _token_set(text)
    if not pf_tokens:
        return {
            "patent_family_id": patent_family_id,
            "claim_scope_summary": pf["summary"],
            "matches": [],
            "created_relations": [],
            "note": "专利族没有 claim_scope_summary / title，无法匹配",
        }

    scored = []
    for c in claims:
        sim = _jaccard(pf_tokens, _token_set(c["text"]))
        if sim >= similarity_threshold:
            scored.append({
                "claim_id": c["cid"],
                "claim_text": c["text"][:120],
                "claim_type": c["ctype"],
                "similarity": round(sim, 3),
            })
    scored.sort(key=lambda x: -x["similarity"])
    scored = scored[:top_k]

    created = []
    if persist:
        with driver.session() as s:
            for m in scored:
                existing = s.run("""
                    MATCH (pf:PatentFamily {patent_family_id: $pfid})-[r:MAPS_TO]->(tc:TechnicalClaim {claim_id: $cid})
                    RETURN r.mapping_id AS mid LIMIT 1
                """, pfid=patent_family_id, cid=m["claim_id"]).single()
                if existing:
                    m["already_mapped"] = True
                    m["mapping_id"] = existing["mid"]
                    continue

                mid = f"IPMAP:{uuid.uuid4().hex[:8].upper()}"
                s.run("""
                    MATCH (pf:PatentFamily {patent_family_id: $pfid})
                    MATCH (tc:TechnicalClaim {claim_id: $cid})
                    CREATE (pf)-[r:MAPS_TO {
                        mapping_id: $mid,
                        similarity: $sim,
                        threshold: $thr,
                        created_at: datetime()
                    }]->(tc)
                """, pfid=patent_family_id, cid=m["claim_id"],
                     mid=mid, sim=m["similarity"], thr=similarity_threshold)

                m["already_mapped"] = False
                m["mapping_id"] = mid
                created.append({"mapping_id": mid, "claim_id": m["claim_id"], "similarity": m["similarity"]})

        if created:
            write_audit_event(
                driver,
                action_type="LINK_CREATE",
                object_type="PatentFamily",
                object_id=patent_family_id,
                actor_id=actor_id,
                delta={"created_mappings": created},
                reason=f"专利-论文映射：{len(created)} 条",
            )

    return {
        "patent_family_id": patent_family_id,
        "claim_scope_summary": pf["summary"],
        "matches": scored,
        "created_relations": created,
    }


def batch_map_all_patents(
    driver: Driver,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    top_k: int = 5,
    limit: int = 100,
    actor_id: str = "ip_mapping",
) -> Dict:
    """对所有 PatentFamily 批量映射"""
    with driver.session() as s:
        pfids = [r["pfid"] for r in s.run("""
            MATCH (pf:PatentFamily)
            WHERE pf.claim_scope_summary IS NOT NULL AND pf.claim_scope_summary <> ''
            RETURN pf.patent_family_id AS pfid
            LIMIT $limit
        """, limit=limit)]

    total_created = 0
    details = []
    for pfid in pfids:
        try:
            r = map_patent_to_claims(
                driver, pfid,
                similarity_threshold=similarity_threshold,
                top_k=top_k,
                actor_id=actor_id,
                persist=True,
            )
            total_created += len(r["created_relations"])
            details.append({
                "patent_family_id": pfid,
                "matches": len(r["matches"]),
                "created": len(r["created_relations"]),
            })
        except Exception as e:
            details.append({"patent_family_id": pfid, "error": str(e)})

    return {
        "total_patents_processed": len(pfids),
        "total_mappings_created": total_created,
        "details": details,
    }


def list_mappings_for_patent(driver: Driver, patent_family_id: str) -> List[Dict]:
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (pf:PatentFamily {patent_family_id: $pfid})-[r:MAPS_TO]->(tc:TechnicalClaim)
            RETURN r.mapping_id AS mapping_id,
                   r.similarity AS similarity,
                   tc.claim_id AS claim_id,
                   tc.claim_type AS claim_type,
                   tc.claim_text AS claim_text
            ORDER BY r.similarity DESC
        """, pfid=patent_family_id))
    return [dict(r) for r in rows]