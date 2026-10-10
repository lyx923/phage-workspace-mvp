# src/ci/entity_resolution.py
"""
MCI-13 实体消歧服务

能力：
- 名称/别名/域名多维查重
- 子公司 / 母公司 / 品牌 / 更名关系建模（OWNS_OR_CONTROLS）
- 合作伙伴关系建模（PARTNERS_WITH）

保守策略：不自动合并，只给出"疑似重复"或"关系建议"，由人工确认。
"""
from __future__ import annotations

import re
import uuid
from typing import Dict, List, Optional
from urllib.parse import urlparse

from neo4j import Driver
from src.shared.audit_service import write_audit_event


def _normalize_name(name: str) -> str:
    """
    归一化组织名称，用于相似度比较。

    处理：
        - 转小写、去首尾空格
        - 去掉常见公司后缀（Inc / Ltd / GmbH / Pharma / Biotech 等）
        - 去掉所有非字母数字和中文的字符
    """
    if not name:
        return ""
    n = name.strip().lower()
    for suffix in [", inc.", " inc.", ", inc", " inc", " ltd.", " ltd", " co., ltd.",
                   " gmbh", " sa", " s.a.", " bv", " b.v.", " plc", " corp.", " corp",
                   " corporation", " limited", " pharmaceuticals", " pharma", " biotech"]:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    n = re.sub(r"[^\w\u4e00-\u9fff]+", "", n)
    return n


def _extract_domain(url: str) -> Optional[str]:
    """
    从 URL 中提取域名（去掉 www. 前缀，转小写）。
    无法解析时返回 None。
    """
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
    """
    把字符串切成 token 集合（只保留长度 >=2 的字母数字/中文片段）。
    用于 Jaccard 相似度计算。
    """
    if not s:
        return set()
    return set(re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", s.lower()))


def _jaccard(a: set, b: set) -> float:
    """计算两个集合的 Jaccard 相似度；任一为空返回 0.0。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_duplicate_candidates(driver, organization_id, min_score=0.5):
    """
    查找与目标组织疑似重复的其他组织。

    打分规则：
        - 归一化名称相同          +1.0
        - 名称 token Jaccard >=0.5 + 0.6 * j
        - 官网域名相同            +0.8
        - 有共享别名              +0.7
        - 名称存在子串关系        +0.4
    总分 >= min_score 时输出为候选。

    Args:
        driver: Neo4j 驱动
        organization_id: 目标组织 ID
        min_score: 最低分阈值

    Returns:
        List[Dict]: 候选列表，按分数倒序
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

    # 预计算目标组织特征
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

        # 归一化名称完全相同
        if t_name and t_name == o_name:
            score += 1.0
            reasons.append("canonical_name 归一化后相同")
        # token Jaccard
        j = _jaccard(t_tokens, o_tokens)
        if j >= 0.5:
            score += 0.6 * j
            reasons.append(f"名称 token Jaccard={j:.2f}")
        # 域名相同
        if t_domain and o_domain and t_domain == o_domain:
            score += 0.8
            reasons.append(f"官网域名相同: {t_domain}")
        # 共享别名
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


# 允许的关系类型（OWNS_OR_CONTROLS）
ALLOWED_RELATION_TYPES = {"parent_of", "subsidiary_of", "brand_of", "renamed_to", "acquired"}


def link_organizations(driver, source_org_id, target_org_id, relation_type,
                       note="", actor_id="entity_resolution"):
    """
    建立两个组织之间的控制关系（OWNS_OR_CONTROLS）。

    - 幂等：若关系已存在，返回已有 relation_id
    - 校验 source / target 存在且不同
    - 写审计日志

    Args:
        source_org_id: 源组织
        target_org_id: 目标组织
        relation_type: parent_of / subsidiary_of / brand_of / renamed_to / acquired
        note: 备注
        actor_id: 操作者

    Returns:
        str: relation_id
    """
    if relation_type not in ALLOWED_RELATION_TYPES:
        raise ValueError(f"relation_type 必须是 {sorted(ALLOWED_RELATION_TYPES)} 之一")
    if source_org_id == target_org_id:
        raise ValueError("source 和 target 不能相同")

    with driver.session() as s:
        # 校验两端组织存在
        ok = s.run("""
            MATCH (a:Organization {organization_id: $sid})
            MATCH (b:Organization {organization_id: $tid})
            RETURN a.canonical_name AS an, b.canonical_name AS bn
        """, sid=source_org_id, tid=target_org_id).single()
        if not ok:
            raise ValueError("source 或 target 组织不存在")

        # 幂等检查
        existing = s.run("""
            MATCH (a:Organization {organization_id: $sid})-[r:OWNS_OR_CONTROLS]->(b:Organization {organization_id: $tid})
            RETURN r.relation_id AS rid LIMIT 1
        """, sid=source_org_id, tid=target_org_id).single()
        if existing:
            print(f"ℹ️ 关系已存在: {existing['rid']}")
            return existing["rid"]

        # 创建关系
        relation_id = f"ORG-REL:{uuid.uuid4().hex[:8].upper()}"
        s.run("""
            MATCH (a:Organization {organization_id: $sid})
            MATCH (b:Organization {organization_id: $tid})
            CREATE (a)-[r:OWNS_OR_CONTROLS {
                relation_id: $rid, relation_type: $rtype,
                note: $note, created_at: datetime()
            }]->(b)
        """, sid=source_org_id, tid=target_org_id,
             rid=relation_id, rtype=relation_type, note=note)

    write_audit_event(
        driver, action_type="LINK_CREATE",
        object_type="Organization", object_id=source_org_id,
        actor_id=actor_id,
        delta={"relation_id": relation_id, "relation_type": relation_type,
               "relation_kind": "OWNS_OR_CONTROLS",
               "target_organization_id": target_org_id, "note": note},
        reason=f"建立组织关系 {ok['an']} --[{relation_type}]--> {ok['bn']}",
    )
    return relation_id


def list_organization_relations(driver, organization_id):
    """
    列出某组织的所有控制关系（双向）。
    """
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (a:Organization {organization_id: $oid})-[r:OWNS_OR_CONTROLS]-(b:Organization)
            RETURN r.relation_id AS relation_id, r.relation_type AS relation_type,
                   r.note AS note,
                   startNode(r).organization_id AS source_id,
                   startNode(r).canonical_name AS source_name,
                   endNode(r).organization_id AS target_id,
                   endNode(r).canonical_name AS target_name
        """, oid=organization_id))
    return [dict(r) for r in rows]


# 允许的合作关系类型（PARTNERS_WITH）
ALLOWED_PARTNERSHIP_TYPES = {"partner_with", "collaborate_with", "license_in", "license_out"}


def link_partnership(driver, source_org_id, target_org_id,
                     partnership_type="partner_with", note="",
                     direction="outgoing", actor_id="entity_resolution"):
    """
    建立两个组织之间的合作关系（PARTNERS_WITH）。

    - direction="symmetric" 时同时创建反向关系
    - 幂等：已存在则返回已有 partnership_id

    Args:
        source_org_id: 源组织
        target_org_id: 目标组织
        partnership_type: partner_with / collaborate_with / license_in / license_out
        note: 备注
        direction: "outgoing" 或 "symmetric"
        actor_id: 操作者

    Returns:
        str: partnership_id
    """
    if partnership_type not in ALLOWED_PARTNERSHIP_TYPES:
        raise ValueError(f"partnership_type 必须是 {sorted(ALLOWED_PARTNERSHIP_TYPES)} 之一")
    if source_org_id == target_org_id:
        raise ValueError("source 和 target 不能相同")
    if direction not in ("outgoing", "symmetric"):
        raise ValueError("direction 必须是 'outgoing' 或 'symmetric' 之一")

    with driver.session() as s:
        # 校验两端组织存在
        ok = s.run("""
            MATCH (a:Organization {organization_id: $sid})
            MATCH (b:Organization {organization_id: $tid})
            RETURN a.canonical_name AS an, b.canonical_name AS bn
        """, sid=source_org_id, tid=target_org_id).single()
        if not ok:
            raise ValueError("source 或 target 组织不存在")

        # 幂等检查（双向）
        existing = s.run("""
            MATCH (a:Organization {organization_id: $sid})-[r:PARTNERS_WITH]-(b:Organization {organization_id: $tid})
            RETURN r.partnership_id AS pid LIMIT 1
        """, sid=source_org_id, tid=target_org_id).single()
        if existing:
            print(f"ℹ️ 合作关系已存在: {existing['pid']}")
            return existing["pid"]

        partnership_id = f"PARTNERSHIP:{uuid.uuid4().hex[:8].upper()}"
        # 正向关系
        s.run("""
            MATCH (a:Organization {organization_id: $sid})
            MATCH (b:Organization {organization_id: $tid})
            CREATE (a)-[r:PARTNERS_WITH {
                partnership_id: $pid, partnership_type: $ptype,
                note: $note, direction: $direction, created_at: datetime()
            }]->(b)
        """, sid=source_org_id, tid=target_org_id,
             pid=partnership_id, ptype=partnership_type,
             note=note, direction=direction)

        # 双向时补反向
        if direction == "symmetric":
            s.run("""
                MATCH (b:Organization {organization_id: $tid})
                MATCH (a:Organization {organization_id: $sid})
                CREATE (b)-[r:PARTNERS_WITH {
                    partnership_id: $pid, partnership_type: $ptype,
                    note: $note, direction: $direction, created_at: datetime()
                }]->(a)
            """, sid=source_org_id, tid=target_org_id,
                 pid=partnership_id, ptype=partnership_type,
                 note=note, direction=direction)

    write_audit_event(
        driver, action_type="LINK_CREATE",
        object_type="Organization", object_id=source_org_id,
        actor_id=actor_id,
        delta={"partnership_id": partnership_id,
               "partnership_type": partnership_type,
               "relation_kind": "PARTNERS_WITH",
               "target_organization_id": target_org_id,
               "direction": direction, "note": note},
        reason=f"建立合作关系 {ok['an']} --[PARTNERS_WITH/{partnership_type}]--> {ok['bn']}",
    )
    return partnership_id


def list_partnerships(driver, organization_id):
    """
    列出某组织的所有合作关系（双向）。
    """
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (a:Organization {organization_id: $oid})-[r:PARTNERS_WITH]-(b:Organization)
            RETURN r.partnership_id AS partnership_id,
                   r.partnership_type AS partnership_type,
                   r.note AS note, r.direction AS direction,
                   startNode(r).organization_id AS source_id,
                   startNode(r).canonical_name AS source_name,
                   endNode(r).organization_id AS target_id,
                   endNode(r).canonical_name AS target_name
        """, oid=organization_id))
    return [dict(r) for r in rows]