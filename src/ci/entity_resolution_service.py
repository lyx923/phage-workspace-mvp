# src/ci/entity_resolution_service.py
"""
MCI-13 实体消歧服务

能力：
- 名称/别名/域名多维查重
- 子公司 / 母公司 / 品牌 / 更名关系建模
- 保守策略：不自动合并，只给出"疑似重复"或"关系建议"，由人工确认

边界：
- 不自动 merge 节点
- 不自动删除任何节点
- 所有关系建立都写 AuditEvent
"""
from __future__ import annotations

import re
import uuid
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from neo4j import Driver

from src.shared.audit_service import write_audit_event


# ============================================================
# 工具
# ============================================================

def _normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.strip().lower()
    # 去掉常见后缀
    for suffix in [", inc.", " inc.", ", inc", " inc", " ltd.", " ltd", " co., ltd.",
                   " gmbh", " sa", " s.a.", " bv", " b.v.", " plc", " corp.", " corp",
                   " corporation", " limited", " pharmaceuticals", " pharma", " biotech"]:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    n = re.sub(r"[^\w\u4e00-\u9fff]+", "", n)
    return n


def _extract_domain(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def _token_set(s: str) -> set:
    if not s:
        return set()
    return set(re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", s.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ============================================================
# 查重
# ============================================================

def find_duplicate_candidates(
    driver: Driver,
    organization_id: str,
    min_score: float = 0.5,
) -> List[Dict]:
    """
    给定一个组织，返回可能与它重复的其他组织列表。

    评分维度：
    - 名称归一化后完全一致：+1.0
    - 名称 token Jaccard ≥ 0.5：+0.6 * Jaccard
    - 域名一致：+0.8
    - 有共同 alias：+0.7
    - 一方是另一方的子串（≥6 字符）：+0.4

    返回按 score 倒序的列表（不含自身）。
    """
    with driver.session() as s:
        target = s.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.organization_id AS oid, o.canonical_name AS name,
                   o.aliases AS aliases, o.website AS website
        """, oid=organization_id).single()
        if not target:
            return []

        all_orgs = list(s.run("""
            MATCH (o:Organization)
            WHERE o.organization_id <> $oid
            RETURN o.organization_id AS oid, o.canonical_name AS name,
                   o.aliases AS aliases, o.website AS website
        """, oid=organization_id))

    t_name = _normalize_name(target["name"] or "")
    t_aliases = set((a or "").lower() for a in (target["aliases"] or []))
    t_domain = _extract_domain(target["website"] or "")
    t_tokens = _token_set(target["name"] or "")

    results = []
    for org in all_orgs:
        score = 0.0
        reasons = []

        o_name = _normalize_name(org["name"] or "")
        o_aliases = set((a or "").lower() for a in (org["aliases"] or []))
        o_domain = _extract_domain(org["website"] or "")
        o_tokens = _token_set(org["name"] or "")

        # 名称完全相同
        if t_name and t_name == o_name:
            score += 1.0
            reasons.append("canonical_name 归一化后相同")

        # token Jaccard
        j = _jaccard(t_tokens, o_tokens)
        if j >= 0.5:
            score += 0.6 * j
            reasons.append(f"名称 token Jaccard={j:.2f}")

        # 域名
        if t_domain and o_domain and t_domain == o_domain:
            score += 0.8
            reasons.append(f"官网域名相同: {t_domain}")

        # alias 交集
        common_alias = t_aliases & o_aliases
        if common_alias:
            score += 0.7
            reasons.append(f"共享别名: {list(common_alias)[:3]}")

        # 子串关系
        if t_name and o_name and len(t_name) >= 6 and len(o_name) >= 6:
            if t_name in o_name or o_name in t_name:
                score += 0.4
                reasons.append("名称存在子串关系")

        if score >= min_score:
            results.append({
                "candidate_organization_id": org["oid"],
                "candidate_canonical_name": org["name"],
                "score": round(min(score, 1.0), 3),
                "reasons": reasons,
            })

    results.sort(key=lambda x: -x["score"])
    return results


# ============================================================
# 关系建模
# ============================================================

ALLOWED_RELATION_TYPES = {"parent_of", "subsidiary_of", "brand_of", "renamed_to", "acquired"}


def link_organizations(
    driver: Driver,
    source_org_id: str,
    target_org_id: str,
    relation_type: str,
    note: str = "",
    actor_id: str = "entity_resolution",
) -> str:
    """
    建立两个组织之间的关系 (Organization)-[:OWNS_OR_CONTROLS]->(Organization)。

    参数：
        source_org_id: 主动方（如母公司 / 品牌方 / 收购方）
        target_org_id: 被动方（如子公司 / 品牌 / 被收购方）
        relation_type: parent_of / subsidiary_of / brand_of / renamed_to / acquired

    返回：relation_id (供审计用)
    """
    if relation_type not in ALLOWED_RELATION_TYPES:
        raise ValueError(f"relation_type 必须是 {sorted(ALLOWED_RELATION_TYPES)} 之一")
    if source_org_id == target_org_id:
        raise ValueError("source 和 target 不能相同")

    with driver.session() as s:
        ok = s.run("""
            MATCH (a:Organization {organization_id: $sid})
            MATCH (b:Organization {organization_id: $tid})
            RETURN a.canonical_name AS an, b.canonical_name AS bn
        """, sid=source_org_id, tid=target_org_id).single()
        if not ok:
            raise ValueError("source 或 target 组织不存在")

        existing = s.run("""
            MATCH (a:Organization {organization_id: $sid})-[r:OWNS_OR_CONTROLS]->(b:Organization {organization_id: $tid})
            RETURN r.relation_id AS rid LIMIT 1
        """, sid=source_org_id, tid=target_org_id).single()
        if existing:
            print(f"ℹ️ 关系已存在: {existing['rid']}")
            return existing["rid"]

        relation_id = f"ORG-REL:{uuid.uuid4().hex[:8].upper()}"
        s.run("""
            MATCH (a:Organization {organization_id: $sid})
            MATCH (b:Organization {organization_id: $tid})
            CREATE (a)-[r:OWNS_OR_CONTROLS {
                relation_id: $rid,
                relation_type: $rtype,
                note: $note,
                created_at: datetime()
            }]->(b)
        """, sid=source_org_id, tid=target_org_id,
             rid=relation_id, rtype=relation_type, note=note)

    write_audit_event(
        driver,
        action_type="LINK_CREATE",
        object_type="Organization",
        object_id=source_org_id,
        actor_id=actor_id,
        delta={
            "relation_id": relation_id,
            "relation_type": relation_type,
            "target_organization_id": target_org_id,
            "note": note,
        },
        reason=f"建立组织关系 {ok['an']} --[{relation_type}]--> {ok['bn']}",
    )
    return relation_id


def list_organization_relations(driver: Driver, organization_id: str) -> List[Dict]:
    """列出某组织的所有 OWNS_OR_CONTROLS 关系（双向）"""
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (a:Organization {organization_id: $oid})-[r:OWNS_OR_CONTROLS]-(b:Organization)
            RETURN r.relation_id AS relation_id,
                   r.relation_type AS relation_type,
                   r.note AS note,
                   startNode(r).organization_id AS source_id,
                   startNode(r).canonical_name AS source_name,
                   endNode(r).organization_id AS target_id,
                   endNode(r).canonical_name AS target_name
        """, oid=organization_id))
    return [dict(r) for r in rows]