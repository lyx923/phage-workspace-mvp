# src/engineering_intelligence/extract_service.py
"""
Action 12.5: 使用 DeepSeek 从指定来源中提取待审核的技术候选对象

PRD 12.5 要求：
- 输入：source_artifact_id, source_text, extraction_schema_version
- 输出：candidate_claims / candidate_constructs / candidate_strategies / candidate_results
- DeepSeek 只产生"候选对象"，默认 review_status = pending
- 必须保留原文位置或原文片段
- 未通过审核不得进入正式简报

边界：
- 不生成可执行的工程化噬菌体操作方案
- 不自动判断技术有效性
- 不将专利权利要求等同为实验验证
- 不做事实判定；LLM 只做抽取
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Driver
from openai import OpenAI

from config import Config
from src.shared.audit_service import write_audit_event


# ============================================================
# 受控值（与 schema.py 中的 ControlledVocabulary 对齐）
# ============================================================

EXTRACTION_SCHEMA_VERSION = "v1.0"

ALLOWED_CLAIM_TYPES = {"efficacy", "host_range", "safety", "manufacturability", "mechanism"}
ALLOWED_RESULT_TYPES = {"host_range", "lysis", "biofilm", "safety", "in_vivo", "computational"}
ALLOWED_STUDY_CONTEXTS = {"in_vitro", "animal", "clinical", "computational"}
ALLOWED_OUTCOME_DIRECTIONS = {"positive", "negative", "mixed", "neutral"}
ALLOWED_CLAIMANT_TYPES = {"publication", "patent", "company", "investigator"}
ALLOWED_CONSTRUCT_STATUSES = {
    "proposed", "built", "in_vitro_tested", "in_vivo_tested", "clinical"
}
ALLOWED_STRATEGY_TYPES = {
    "host_range_expansion", "tail_fiber_engineering", "receptor_binding_engineering",
    "lysis_enhancement", "lysogeny_removal", "biofilm_disruption", "payload_delivery",
    "anti_resistance_payload", "anti_virulence_payload", "immune_modulation",
    "phage_display", "genome_minimization", "manufacturability_optimization",
    "stability_optimization", "delivery_optimization", "other",
}

# 候选类型 → (Neo4j Label, 主键属性名)
CANDIDATE_TYPES = {
    "claim":     {"label": "TechnicalClaim",           "id_prop": "claim_id"},
    "result":    {"label": "TechnicalResult",          "id_prop": "result_id"},
    "construct": {"label": "EngineeredPhageConstruct", "id_prop": "construct_id"},
    "strategy":  {"label": "EngineeringStrategy",      "id_prop": "strategy_id"},
}


# ============================================================
# LLM 客户端
# ============================================================

def _get_client() -> OpenAI:
    return OpenAI(api_key=Config.DS_API_KEY, base_url=Config.DS_BASE_URL)


_SYSTEM_PROMPT = """你是噬菌体技术情报抽取助手。你的任务是从给定的论文、专利或公司公告文本中，抽取"技术候选对象"。

严格要求：
1. 只抽取文本中明确出现的信息。禁止推测、禁止补充背景知识。
2. 所有输出均为"候选对象"，不代表已核实事实。
3. 输出必须是严格的 JSON，不要任何 Markdown 代码块标记。
4. 保留原文位置：每个对象必须带 exact_quote（原文片段，≤200 字）和 char_offset（在给定正文中的起始字符索引；找不到填 null）。
5. 无法确定的字段填空字符串、空数组或 null，不要瞎编。
6. 输出规模控制：candidate_claims ≤ 30，candidate_constructs ≤ 10，
   candidate_strategies ≤ 10，candidate_results ≤ 20。
7. 输出语言与原文保持一致；若原文为中文，claim_text 用中文；若原文为英文，claim_text 用英文。"""


_USER_TEMPLATE = """来源 URL：{url}
来源标题：{title}
来源类型：{source_type}

正文（前 {max_chars} 字）：
{content}

请严格按以下 JSON 结构输出抽取结果：

{{
  "candidate_strategies": [
    {{
      "strategy_type": "受控词表枚举之一",
      "description": "该策略在原文中的一句话描述",
      "exact_quote": "原文片段",
      "char_offset": 0
    }}
  ],
  "candidate_constructs": [
    {{
      "public_name": "构建体公开名称",
      "construct_code": "公开代号",
      "parent_phage": "亲本噬菌体名称",
      "construct_status": "proposed/built/in_vitro_tested/in_vivo_tested/clinical",
      "target_pathogen_text": "原文中的目标病原菌描述",
      "intended_effects": ["扩宿主谱", "增强裂解"],
      "strategy_refs": ["引用的 strategy_type 列表，需与 candidate_strategies 中的一致"],
      "exact_quote": "原文片段",
      "char_offset": 0
    }}
  ],
  "candidate_claims": [
    {{
      "claim_type": "efficacy/host_range/safety/manufacturability/mechanism",
      "claim_text": "结构化转述，不超过 100 字",
      "exact_quote": "原文片段",
      "char_offset": 0,
      "claimant_type": "publication/patent/company/investigator",
      "evidence_context": "in_vitro/animal/clinical/computational",
      "construct_ref": "引用的 construct 的 public_name（若无则空字符串）",
      "strategy_ref": "引用的 strategy_type（若无则空字符串）"
    }}
  ],
  "candidate_results": [
    {{
      "result_type": "host_range/lysis/biofilm/safety/in_vivo/computational",
      "study_context": "in_vitro/animal/clinical/computational",
      "outcome_direction": "positive/negative/mixed/neutral",
      "metric_name": "指标名",
      "metric_value": 0.0,
      "metric_unit": "单位",
      "sample_size": 0,
      "comparator": "对照",
      "limitation_summary": "原文中明确的局限性",
      "construct_ref": "引用的 construct 的 public_name（若无则空字符串）",
      "exact_quote": "原文片段",
      "char_offset": 0
    }}
  ]
}}

规则：
- strategy_type 必须从以下受控词表中选一个：
  host_range_expansion / tail_fiber_engineering / receptor_binding_engineering /
  lysis_enhancement / lysogeny_removal / biofilm_disruption / payload_delivery /
  anti_resistance_payload / anti_virulence_payload / immune_modulation /
  phage_display / genome_minimization / manufacturability_optimization /
  stability_optimization / delivery_optimization / other
- claim_type / result_type / study_context / outcome_direction / claimant_type
  必须从对应枚举中选一个，否则该条不输出。
- 数值型字段找不到就填 null，不要瞎编。
- exact_quote 必须是正文中真实出现的片段（可直接复制粘贴的连续字符串）。
- 只输出 JSON，不要任何解释文字。"""


# ============================================================
# JSON 修复（与 ci.py / monitor_runner.py 同款策略）
# ============================================================

def _repair_json(s: str) -> Optional[dict]:
    if not s or not s.strip():
        return None
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    max_trim = min(2000, len(s) - 10)
    for trim in range(max_trim):
        cand = s if trim == 0 else s[:-trim]
        cand = cand.rstrip()
        while cand and cand[-1] in ",:":
            cand = cand[:-1].rstrip()
        in_str = False
        esc = False
        for ch in cand:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
        if in_str:
            cand += '"'
        ob = cand.count("[") - cand.count("]")
        oc = cand.count("{") - cand.count("}")
        if ob < 0 or oc < 0:
            continue
        cand = cand + ("]" * ob) + ("}" * oc)
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


# ============================================================
# 抽取
# ============================================================

def _call_llm(url: str, title: str, source_type: str,
              content: str, max_chars: int = 8000) -> dict:
    client = _get_client()
    user_prompt = _USER_TEMPLATE.format(
        url=url or "",
        title=title or "",
        source_type=source_type or "unknown",
        max_chars=max_chars,
        content=content[:max_chars],
    )
    resp = client.chat.completions.create(
        model=Config.DS_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fixed = _repair_json(raw)
        if fixed is not None:
            fixed["_repaired"] = True
            return fixed
        return {
            "candidate_claims": [],
            "candidate_constructs": [],
            "candidate_strategies": [],
            "candidate_results": [],
            "_parse_error": raw[-500:] if raw else "",
        }


def _validate_and_normalize(candidates: dict) -> dict:
    """过滤非法枚举值，归一化字段，并给出统计。"""
    def _norm_enum(v, allowed):
        if v is None:
            return None
        v = str(v).strip().lower()
        return v if v in allowed else None

    strategies = []
    for s in candidates.get("candidate_strategies", []) or []:
        st = _norm_enum(s.get("strategy_type"), ALLOWED_STRATEGY_TYPES)
        if not st:
            continue
        strategies.append({
            "strategy_type": st,
            "description": (s.get("description") or "").strip()[:200],
            "exact_quote": (s.get("exact_quote") or "").strip()[:400],
            "char_offset": s.get("char_offset"),
        })

    constructs = []
    for c in candidates.get("candidate_constructs", []) or []:
        status = _norm_enum(c.get("construct_status"), ALLOWED_CONSTRUCT_STATUSES) or "proposed"
        strategy_refs = [
            x for x in (c.get("strategy_refs") or [])
            if x in ALLOWED_STRATEGY_TYPES
        ]
        constructs.append({
            "public_name": (c.get("public_name") or "").strip()[:120],
            "construct_code": (c.get("construct_code") or "").strip()[:120],
            "parent_phage": (c.get("parent_phage") or "").strip()[:120],
            "construct_status": status,
            "target_pathogen_text": (c.get("target_pathogen_text") or "").strip()[:200],
            "intended_effects": [
                str(x).strip()[:80] for x in (c.get("intended_effects") or []) if x
            ][:20],
            "strategy_refs": strategy_refs,
            "exact_quote": (c.get("exact_quote") or "").strip()[:400],
            "char_offset": c.get("char_offset"),
        })

    claims = []
    for cl in candidates.get("candidate_claims", []) or []:
        ct = _norm_enum(cl.get("claim_type"), ALLOWED_CLAIM_TYPES)
        if not ct:
            continue
        claimant = _norm_enum(cl.get("claimant_type"), ALLOWED_CLAIMANT_TYPES) or "publication"
        ctx = _norm_enum(cl.get("evidence_context"), ALLOWED_STUDY_CONTEXTS)
        claim_text = (cl.get("claim_text") or "").strip()[:400]
        if not claim_text:
            continue
        claims.append({
            "claim_type": ct,
            "claim_text": claim_text,
            "exact_quote": (cl.get("exact_quote") or "").strip()[:400],
            "char_offset": cl.get("char_offset"),
            "claimant_type": claimant,
            "evidence_context": ctx,
            "construct_ref": (cl.get("construct_ref") or "").strip()[:120],
            "strategy_ref": (cl.get("strategy_ref") or "").strip()[:80],
        })

    results = []
    for r in candidates.get("candidate_results", []) or []:
        rt = _norm_enum(r.get("result_type"), ALLOWED_RESULT_TYPES)
        sc = _norm_enum(r.get("study_context"), ALLOWED_STUDY_CONTEXTS)
        od = _norm_enum(r.get("outcome_direction"), ALLOWED_OUTCOME_DIRECTIONS)
        if not (rt and sc):
            continue
        try:
            mv = float(r.get("metric_value")) if r.get("metric_value") is not None else None
        except (TypeError, ValueError):
            mv = None
        try:
            ss = int(r.get("sample_size")) if r.get("sample_size") is not None else None
        except (TypeError, ValueError):
            ss = None
        results.append({
            "result_type": rt,
            "study_context": sc,
            "outcome_direction": od,
            "metric_name": (r.get("metric_name") or "").strip()[:80],
            "metric_value": mv,
            "metric_unit": (r.get("metric_unit") or "").strip()[:30],
            "sample_size": ss,
            "comparator": (r.get("comparator") or "").strip()[:80],
            "limitation_summary": (r.get("limitation_summary") or "").strip()[:300],
            "construct_ref": (r.get("construct_ref") or "").strip()[:120],
            "exact_quote": (r.get("exact_quote") or "").strip()[:400],
            "char_offset": r.get("char_offset"),
        })

    return {
        "candidate_strategies": strategies,
        "candidate_constructs": constructs,
        "candidate_claims": claims,
        "candidate_results": results,
    }


def extract_technical_candidates(
    driver: Driver,
    source_artifact_id: str,
    source_text: str,
    extraction_schema_version: str = EXTRACTION_SCHEMA_VERSION,
    actor_id: str = "deepseek_extractor",
) -> Dict[str, Any]:
    """
    Action 12.5 主入口。

    输入：
        source_artifact_id：SourceArtifact.source_id
        source_text：原始文本（论文/专利/公告全文或摘要）
        extraction_schema_version：抽取模式版本

    输出：
        {
          "source_artifact_id": "...",
          "schema_version": "v1.0",
          "extracted_at": "...",
          "candidates": {...},   # 归一化后的候选对象
          "stats": {...}         # 抽取统计
        }

    注意：本函数只做抽取，不落库。落库请调用 persist_candidates()。
    """
    if not source_text or not source_text.strip():
        raise ValueError("source_text 为空，无法抽取")

    with driver.session() as s:
        rec = s.run("""
            MATCH (src:SourceArtifact {source_id: $sid})
            RETURN src.source_id AS sid,
                   src.title AS title,
                   src.url AS url,
                   src.source_type AS source_type
        """, sid=source_artifact_id).single()
    if not rec:
        raise ValueError(f"SourceArtifact {source_artifact_id} 不存在")

    raw = _call_llm(
        url=rec["url"] or "",
        title=rec["title"] or "",
        source_type=rec["source_type"] or "unknown",
        content=source_text,
    )
    normalized = _validate_and_normalize(raw)

    stats = {
        "strategies": len(normalized["candidate_strategies"]),
        "constructs": len(normalized["candidate_constructs"]),
        "claims": len(normalized["candidate_claims"]),
        "results": len(normalized["candidate_results"]),
        "repaired": bool(raw.get("_repaired")),
        "parse_error": bool(raw.get("_parse_error")),
    }

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="TechnicalCandidateExtraction",
        object_id=f"EXT:{uuid.uuid4().hex[:8].upper()}",
        actor_id=actor_id,
        delta={
            "source_artifact_id": source_artifact_id,
            "schema_version": extraction_schema_version,
            **stats,
        },
        reason=f"DeepSeek 抽取技术候选对象：{stats}",
    )

    return {
        "source_artifact_id": source_artifact_id,
        "schema_version": extraction_schema_version,
        "extracted_at": datetime.now().isoformat(),
        "candidates": normalized,
        "stats": stats,
    }


# ============================================================
# 落库（全部 review_status = 'pending'）
# ============================================================

def _gen_claim_id() -> str:
    return f"ENG:CLAIM:{uuid.uuid4().hex[:8].upper()}"


def _gen_result_id() -> str:
    return f"ENG:RESULT:{uuid.uuid4().hex[:8].upper()}"


def _gen_construct_id() -> str:
    return f"ENG:CONST:{uuid.uuid4().hex[:8].upper()}"


def _gen_strategy_id() -> str:
    return f"ENG:STRAT:{uuid.uuid4().hex[:8].upper()}"


def persist_candidates(
    driver: Driver,
    extraction_result: Dict[str, Any],
    actor_id: str = "deepseek_extractor",
) -> Dict[str, List[str]]:
    """
    把抽取出的候选对象落库：
    - 全部 review_status = 'pending'
    - 全部 extracted_by = 'deepseek'
    - 保留 exact_quote / char_offset / source_artifact_id
    - 每条候选同时创建 pending Review 节点

    返回：{"claim_ids": [...], "result_ids": [...],
            "construct_ids": [...], "strategy_ids": [...]}
    """
    sid = extraction_result["source_artifact_id"]
    schema_version = extraction_result.get("schema_version", EXTRACTION_SCHEMA_VERSION)
    cand = extraction_result["candidates"]

    out = {
        "strategy_ids": [],
        "construct_ids": [],
        "claim_ids": [],
        "result_ids": [],
    }

    # 名称 → ID 映射（用于 construct_ref / strategy_ref 关联）
    strategy_type_to_id: Dict[str, str] = {}
    construct_name_to_id: Dict[str, str] = {}

    with driver.session() as s:
        # 校验 SourceArtifact 存在
        ok = s.run(
            "MATCH (src:SourceArtifact {source_id: $sid}) RETURN src.source_id AS x",
            sid=sid,
        ).single()
        if not ok:
            raise ValueError(f"SourceArtifact {sid} 不存在")

        # ---------- 1. 策略 ----------
        for st in cand.get("candidate_strategies", []):
            stype = st["strategy_type"]
            # 幂等：已存在同类型策略则复用
            existing = s.run("""
                MATCH (es:EngineeringStrategy {strategy_type: $st})
                RETURN es.strategy_id AS sid
                LIMIT 1
            """, st=stype).single()
            if existing:
                strategy_type_to_id[stype] = existing["sid"]
                # 仍补充一条来源引用
                s.run("""
                    MATCH (es:EngineeringStrategy {strategy_id: $eid})
                    MATCH (src:SourceArtifact {source_id: $sid})
                    MERGE (es)-[:SUPPORTED_BY]->(src)
                """, eid=existing["sid"], sid=sid)
                # ✅ 复用也记录到输出
                if existing["sid"] not in out["strategy_ids"]:
                    out["strategy_ids"].append(existing["sid"])
                continue

            str_id = _gen_strategy_id()
            s.run("""
                CREATE (es:EngineeringStrategy {
                    strategy_id: $eid,
                    strategy_type: $stype,
                    description: $desc,
                    evidence_maturity: 'conceptual',
                    review_status: 'pending',
                    extracted_by: 'deepseek',
                    extraction_schema_version: $ver,
                    source_artifact_id: $sid,
                    exact_quote: $quote,
                    char_offset: $offset,
                    created_at: datetime(),
                    updated_at: datetime()
                })
            """, eid=str_id, stype=stype,
                 desc=st["description"] or "",
                 ver=schema_version,
                 sid=sid,
                 quote=st["exact_quote"] or "",
                 offset=st["char_offset"])
            s.run("""
                MATCH (es:EngineeringStrategy {strategy_id: $eid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (es)-[:SUPPORTED_BY]->(src)
            """, eid=str_id, sid=sid)

            # 建 pending Review
            s.run("""
                MATCH (es:EngineeringStrategy {strategy_id: $eid})
                CREATE (r:Review {
                    review_id: $rid,
                    review_type: 'technical_intelligence_review',
                    target_object_type: 'EngineeringStrategy',
                    target_object_id: $eid,
                    reviewer_id: 'pending',
                    decision: 'pending',
                    comment: '',
                    created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(es)
            """, eid=str_id, rid=f"REV-{uuid.uuid4().hex[:8].upper()}")

            strategy_type_to_id[stype] = str_id
            out["strategy_ids"].append(str_id)

        # ---------- 2. 构建体 ----------
        for c in cand.get("candidate_constructs", []):
            name = c.get("public_name") or c.get("construct_code")
            if not name:
                continue
            # 幂等：同 public_name 已存在则复用
            existing = s.run("""
                MATCH (ec:EngineeredPhageConstruct {public_name: $n})
                RETURN ec.construct_id AS cid
                LIMIT 1
            """, n=name).single()
            if existing:
                construct_name_to_id[name] = existing["cid"]
                s.run("""
                    MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                    MATCH (src:SourceArtifact {source_id: $sid})
                    MERGE (ec)-[:REPORTED_IN]->(src)
                """, cid=existing["cid"], sid=sid)
                # ✅ 复用也记录到输出
                if existing["cid"] not in out["construct_ids"]:
                    out["construct_ids"].append(existing["cid"])
                continue

            cid = _gen_construct_id()
            s.run("""
                CREATE (ec:EngineeredPhageConstruct {
                    construct_id: $cid,
                    public_name: $name,
                    construct_code: $code,
                    construct_status: $status,
                    intended_effects: $effects,
                    target_pathogen_text: $tpt,
                    review_status: 'pending',
                    extracted_by: 'deepseek',
                    extraction_schema_version: $ver,
                    source_artifact_id: $sid,
                    exact_quote: $quote,
                    char_offset: $offset,
                    first_public_date: null,
                    created_at: datetime(),
                    updated_at: datetime()
                })
            """, cid=cid,
                 name=name,
                 code=c.get("construct_code") or "",
                 status=c.get("construct_status") or "proposed",
                 effects=c.get("intended_effects") or [],
                 tpt=c.get("target_pathogen_text") or "",
                 ver=schema_version,
                 sid=sid,
                 quote=c.get("exact_quote") or "",
                 offset=c.get("char_offset"))

            # 关联来源
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (ec)-[:REPORTED_IN]->(src)
            """, cid=cid, sid=sid)

            # 关联策略
            for st_ref in c.get("strategy_refs", []):
                st_id = strategy_type_to_id.get(st_ref)
                if not st_id:
                    continue
                s.run("""
                    MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                    MATCH (es:EngineeringStrategy {strategy_id: $sid})
                    MERGE (ec)-[:IMPLEMENTS]->(es)
                """, cid=cid, sid=st_id)

            # 亲本噬菌体（如存在）
            if c.get("parent_phage"):
                s.run("""
                    MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                    MATCH (ph:Phage)
                    WHERE ph.name = $pname OR ph.phage_id = $pname
                    MERGE (ec)-[:DERIVED_FROM]->(ph)
                """, cid=cid, pname=c["parent_phage"])

            # pending Review
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                CREATE (r:Review {
                    review_id: $rid,
                    review_type: 'technical_intelligence_review',
                    target_object_type: 'EngineeredPhageConstruct',
                    target_object_id: $cid,
                    reviewer_id: 'pending',
                    decision: 'pending',
                    comment: '',
                    created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(ec)
            """, cid=cid, rid=f"REV-{uuid.uuid4().hex[:8].upper()}")

            construct_name_to_id[name] = cid
            out["construct_ids"].append(cid)

        # ---------- 3. 主张 ----------
        for cl in cand.get("candidate_claims", []):
            # 幂等：同 claim_text 已存在则跳过
            existing = s.run("""
                MATCH (tc:TechnicalClaim {claim_text: $t})
                RETURN tc.claim_id AS cid LIMIT 1
            """, t=cl["claim_text"]).single()
            if existing:
                continue

            clm_id = _gen_claim_id()
            s.run("""
                CREATE (tc:TechnicalClaim {
                    claim_id: $cid,
                    claim_type: $ctype,
                    claim_text: $text,
                    exact_quote: $quote,
                    char_offset: $offset,
                    claimant_type: $claimant,
                    evidence_context: $ctx,
                    claim_status: 'asserted',
                    confidence: 'medium',
                    review_status: 'pending',
                    extracted_by: 'deepseek',
                    extraction_schema_version: $ver,
                    source_artifact_id: $sid,
                    created_at: datetime(),
                    updated_at: datetime()
                })
            """, cid=clm_id,
                 ctype=cl["claim_type"],
                 text=cl["claim_text"],
                 quote=cl["exact_quote"] or "",
                 offset=cl["char_offset"],
                 claimant=cl["claimant_type"],
                 ctx=cl.get("evidence_context"),
                 ver=schema_version,
                 sid=sid)

            # 关联来源
            s.run("""
                MATCH (tc:TechnicalClaim {claim_id: $cid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (tc)-[:SUPPORTED_BY]->(src)
            """, cid=clm_id, sid=sid)

            # 关联构建体
            if cl.get("construct_ref"):
                c_id = construct_name_to_id.get(cl["construct_ref"])
                if c_id:
                    s.run("""
                        MATCH (tc:TechnicalClaim {claim_id: $cid})
                        MATCH (ec:EngineeredPhageConstruct {construct_id: $eid})
                        MERGE (tc)-[:CLAIMS_ABOUT]->(ec)
                    """, cid=clm_id, eid=c_id)

            # 关联策略
            if cl.get("strategy_ref"):
                st_id = strategy_type_to_id.get(cl["strategy_ref"])
                if st_id:
                    s.run("""
                        MATCH (tc:TechnicalClaim {claim_id: $cid})
                        MATCH (es:EngineeringStrategy {strategy_id: $sid})
                        MERGE (tc)-[:CLAIMS_ABOUT]->(es)
                    """, cid=clm_id, sid=st_id)

            # pending Review
            s.run("""
                MATCH (tc:TechnicalClaim {claim_id: $cid})
                CREATE (r:Review {
                    review_id: $rid,
                    review_type: 'technical_intelligence_review',
                    target_object_type: 'TechnicalClaim',
                    target_object_id: $cid,
                    reviewer_id: 'pending',
                    decision: 'pending',
                    comment: '',
                    created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(tc)
            """, cid=clm_id, rid=f"REV-{uuid.uuid4().hex[:8].upper()}")

            out["claim_ids"].append(clm_id)

        # ---------- 4. 结果 ----------
        for r_ in cand.get("candidate_results", []):
            res_id = _gen_result_id()
            s.run("""
                CREATE (tr:TechnicalResult {
                    result_id: $rid,
                    result_type: $rtype,
                    study_context: $ctx,
                    outcome_direction: $od,
                    metric_name: $mn,
                    metric_value: $mv,
                    metric_unit: $mu,
                    comparator: $cmp,
                    sample_size: $ss,
                    limitation_summary: $lim,
                    reproducibility_status: 'single_source',
                    review_status: 'pending',
                    extracted_by: 'deepseek',
                    extraction_schema_version: $ver,
                    source_artifact_id: $sid,
                    exact_quote: $quote,
                    char_offset: $offset,
                    created_at: datetime(),
                    updated_at: datetime()
                })
            """, rid=res_id,
                 rtype=r_["result_type"],
                 ctx=r_["study_context"],
                 od=r_.get("outcome_direction"),
                 mn=r_.get("metric_name") or "",
                 mv=r_.get("metric_value"),
                 mu=r_.get("metric_unit") or "",
                 cmp=r_.get("comparator") or "",
                 ss=r_.get("sample_size"),
                 lim=r_.get("limitation_summary") or "",
                 ver=schema_version,
                 sid=sid,
                 quote=r_.get("exact_quote") or "",
                 offset=r_.get("char_offset"))

            # 来源
            s.run("""
                MATCH (tr:TechnicalResult {result_id: $rid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (tr)-[:REPORTED_IN]->(src)
            """, rid=res_id, sid=sid)

            # 关联构建体
            if r_.get("construct_ref"):
                c_id = construct_name_to_id.get(r_["construct_ref"])
                if c_id:
                    s.run("""
                        MATCH (tr:TechnicalResult {result_id: $rid})
                        MATCH (ec:EngineeredPhageConstruct {construct_id: $eid})
                        MERGE (tr)-[:RESULT_FOR]->(ec)
                    """, rid=res_id, eid=c_id)

            # pending Review
            s.run("""
                MATCH (tr:TechnicalResult {result_id: $rid})
                CREATE (r:Review {
                    review_id: $rid2,
                    review_type: 'technical_intelligence_review',
                    target_object_type: 'TechnicalResult',
                    target_object_id: $rid,
                    reviewer_id: 'pending',
                    decision: 'pending',
                    comment: '',
                    created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(tr)
            """, rid=res_id, rid2=f"REV-{uuid.uuid4().hex[:8].upper()}")

            out["result_ids"].append(res_id)

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="TechnicalCandidatePersist",
        object_id=f"PERSIST:{uuid.uuid4().hex[:8].upper()}",
        actor_id=actor_id,
        delta={
            "source_artifact_id": sid,
            "strategy_ids": out["strategy_ids"],
            "construct_ids": out["construct_ids"],
            "claim_ids": out["claim_ids"],
            "result_ids": out["result_ids"],
        },
        reason=f"落库技术候选对象：{ {k: len(v) for k, v in out.items()} }",
    )

    return out


# ============================================================
# 待审队列 / 审核
# ============================================================

def list_pending_candidates(driver: Driver, limit: int = 100) -> Dict[str, List[Dict]]:
    """
    列出所有 review_status='pending' 且 extracted_by='deepseek' 的候选对象。
    """
    result = {"strategies": [], "constructs": [], "claims": [], "results": []}
    with driver.session() as s:
        result["strategies"] = [dict(r) for r in s.run("""
            MATCH (es:EngineeringStrategy)
            WHERE es.review_status = 'pending' AND es.extracted_by = 'deepseek'
            RETURN es.strategy_id AS id, es.strategy_type AS strategy_type,
                   es.description AS description, es.exact_quote AS exact_quote,
                   es.source_artifact_id AS source_id, es.created_at AS created_at
            ORDER BY es.created_at DESC LIMIT $limit
        """, limit=limit)]

        result["constructs"] = [dict(r) for r in s.run("""
            MATCH (ec:EngineeredPhageConstruct)
            WHERE ec.review_status = 'pending' AND ec.extracted_by = 'deepseek'
            RETURN ec.construct_id AS id, ec.public_name AS public_name,
                   ec.construct_status AS status,
                   COALESCE(ec.target_pathogen_text, '') AS target,
                   ec.exact_quote AS exact_quote,
                   ec.source_artifact_id AS source_id,
                   ec.created_at AS created_at
            ORDER BY ec.created_at DESC LIMIT $limit
        """, limit=limit)]

        result["claims"] = [dict(r) for r in s.run("""
            MATCH (tc:TechnicalClaim)
            WHERE tc.review_status = 'pending' AND tc.extracted_by = 'deepseek'
            RETURN tc.claim_id AS id, tc.claim_type AS claim_type,
                   tc.claim_text AS claim_text, tc.claimant_type AS claimant_type,
                   tc.evidence_context AS ctx, tc.exact_quote AS exact_quote,
                   tc.source_artifact_id AS source_id, tc.created_at AS created_at
            ORDER BY tc.created_at DESC LIMIT $limit
        """, limit=limit)]

        result["results"] = [dict(r) for r in s.run("""
            MATCH (tr:TechnicalResult)
            WHERE tr.review_status = 'pending' AND tr.extracted_by = 'deepseek'
            RETURN tr.result_id AS id, tr.result_type AS result_type,
                   tr.study_context AS study_context,
                   tr.outcome_direction AS outcome_direction,
                   tr.metric_name AS metric_name, tr.metric_value AS metric_value,
                   tr.metric_unit AS metric_unit, tr.exact_quote AS exact_quote,
                   tr.source_artifact_id AS source_id, tr.created_at AS created_at
            ORDER BY tr.created_at DESC LIMIT $limit
        """, limit=limit)]

    return result


def approve_candidate(
    driver: Driver,
    candidate_type: str,
    node_id: str,
    reviewer_id: str,
    comment: str = "",
) -> str:
    """
    审核通过一个候选对象：
    - 更新对应 pending Review 的 decision = 'approved'
    - 更新候选对象 review_status = 'approved'
    - 写 AuditEvent
    """
    if candidate_type not in CANDIDATE_TYPES:
        raise ValueError(f"candidate_type 必须是 {list(CANDIDATE_TYPES)} 之一")

    label = CANDIDATE_TYPES[candidate_type]["label"]
    id_prop = CANDIDATE_TYPES[candidate_type]["id_prop"]

    with driver.session() as s:
        check = s.run(
            f"MATCH (n:{label} {{`{id_prop}`: $oid}}) RETURN n", oid=node_id
        ).single()
        if not check:
            raise ValueError(f"{label} {node_id} 不存在")

        s.run(f"""
            MATCH (r:Review)-[:REVIEWS]->(n:{label} {{`{id_prop}`: $oid}})
            WHERE r.reviewer_id = 'pending' OR r.decision = 'pending'
            SET r.decision = 'approved',
                r.reviewer_id = $rid,
                r.comment = $c,
                r.reviewed_at = datetime()
        """, oid=node_id, rid=reviewer_id, c=comment)

        s.run(f"""
            MATCH (n:{label} {{`{id_prop}`: $oid}})
            SET n.review_status = 'approved',
                n.updated_at = datetime()
        """, oid=node_id)

    write_audit_event(
        driver,
        action_type="REVIEW_APPROVE",
        object_type=label,
        object_id=node_id,
        actor_id=reviewer_id,
        delta={"review_status": "approved"},
        reason=comment or f"审核通过 {candidate_type} {node_id}",
    )
    return node_id


def reject_candidate(
    driver: Driver,
    candidate_type: str,
    node_id: str,
    reviewer_id: str,
    comment: str = "",
) -> str:
    """审核拒绝一个候选对象。"""
    if candidate_type not in CANDIDATE_TYPES:
        raise ValueError(f"candidate_type 必须是 {list(CANDIDATE_TYPES)} 之一")

    label = CANDIDATE_TYPES[candidate_type]["label"]
    id_prop = CANDIDATE_TYPES[candidate_type]["id_prop"]

    with driver.session() as s:
        check = s.run(
            f"MATCH (n:{label} {{`{id_prop}`: $oid}}) RETURN n", oid=node_id
        ).single()
        if not check:
            raise ValueError(f"{label} {node_id} 不存在")

        s.run(f"""
            MATCH (r:Review)-[:REVIEWS]->(n:{label} {{`{id_prop}`: $oid}})
            WHERE r.reviewer_id = 'pending' OR r.decision = 'pending'
            SET r.decision = 'rejected',
                r.reviewer_id = $rid,
                r.comment = $c,
                r.reviewed_at = datetime()
        """, oid=node_id, rid=reviewer_id, c=comment)

        s.run(f"""
            MATCH (n:{label} {{`{id_prop}`: $oid}})
            SET n.review_status = 'rejected',
                n.updated_at = datetime()
        """, oid=node_id)

    write_audit_event(
        driver,
        action_type="REVIEW_REJECT",
        object_type=label,
        object_id=node_id,
        actor_id=reviewer_id,
        delta={"review_status": "rejected"},
        reason=comment or f"审核拒绝 {candidate_type} {node_id}",
    )
    return node_id


# ============================================================
# 便捷入口
# ============================================================

def extract_and_persist(
    driver: Driver,
    source_artifact_id: str,
    source_text: str,
    actor_id: str = "deepseek_extractor",
) -> Dict[str, Any]:
    """抽取 + 落库，一步完成。"""
    extraction = extract_technical_candidates(
        driver, source_artifact_id, source_text, actor_id=actor_id
    )
    ids = persist_candidates(driver, extraction, actor_id=actor_id)
    return {
        "extraction": extraction,
        "persisted_ids": ids,
    }