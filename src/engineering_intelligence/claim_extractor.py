# src/engineering_intelligence/claim_extractor.py
"""
TechnicalClaim + DeepSeek 候选抽取（PRD 9.4 / 12.5）

包含两部分：
    Part 1: TechnicalClaim      —— 手工创建技术主张
    Part 2: DeepSeek 候选抽取    —— 从文本抽取技术候选对象并落库

注意：TechnicalResult 相关函数已迁移到 result_extractor.py。

边界原则：
    - 只抽取文本明确出现的信息
    - 所有输出均为"候选对象"，不代表已核实事实
    - 落库后状态为 pending，须人工审核
"""

# ==================================================================
# Part 1: TechnicalClaim (原 claim_extractor.py 的 Claim 部分)
# ==================================================================
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_claim_id() -> str:
    """生成技术主张 ID（格式：ENG:CLAIM:XXXXXXXX）。"""
    return f"ENG:CLAIM:{uuid.uuid4().hex[:8].upper()}"


def create_technical_claim(
    driver: Driver, claim_type: str, claim_text: str,
    exact_quote: Optional[str] = None, claimant_type: str = "publication",
    evidence_context: Optional[str] = None,
    construct_id: Optional[str] = None, strategy_id: Optional[str] = None,
    source_id: Optional[str] = None, actor_id: str = "system",
) -> str:
    """
    手工创建技术主张（TechnicalClaim）。

    - 幂等：claim_text 相同则返回已有 ID
    - 可选建立 CLAIMS_ABOUT（构建体 / 策略）和 SUPPORTED_BY（来源）关系

    Args:
        claim_type: 主张类型（efficacy / host_range / safety / manufacturability / mechanism）
        claim_text: 主张文本
        exact_quote: 原文引用
        claimant_type: 主张方（publication / patent / company / investigator）
        evidence_context: 证据上下文
        construct_id: 关联构建体（可选）
        strategy_id: 关联策略（可选）
        source_id: 支撑来源（可选）
        actor_id: 操作者

    Returns:
        str: claim_id
    """
    claim_id = generate_claim_id()

    with driver.session() as session:
        # 幂等检查
        existing = session.run("""
            MATCH (tc:TechnicalClaim {claim_text: $claim_text})
            RETURN tc.claim_id AS id
        """, claim_text=claim_text).single()
        if existing:
            print(f"ℹ️ 主张已存在，ID: {existing['id']}")
            return existing['id']

        # 创建主张节点
        session.run("""
            CREATE (tc:TechnicalClaim {
                claim_id: $claim_id, claim_type: $claim_type,
                claim_text: $claim_text, exact_quote: $exact_quote,
                claimant_type: $claimant_type,
                evidence_context: $evidence_context,
                claim_status: 'asserted', confidence: 'medium',
                review_status: 'pending', extracted_by: 'human',
                created_at: datetime(), updated_at: datetime()
            })
        """, claim_id=claim_id, claim_type=claim_type, claim_text=claim_text,
             exact_quote=exact_quote, claimant_type=claimant_type,
             evidence_context=evidence_context)

        # 可选：关联构建体
        if construct_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MERGE (tc)-[:CLAIMS_ABOUT]->(ec)
            """, claim_id=claim_id, construct_id=construct_id)
        # 可选：关联策略
        if strategy_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (es:EngineeringStrategy {strategy_id: $strategy_id})
                MERGE (tc)-[:CLAIMS_ABOUT]->(es)
            """, claim_id=claim_id, strategy_id=strategy_id)
        # 可选：关联来源
        if source_id:
            session.run("""
                MATCH (tc:TechnicalClaim {claim_id: $claim_id})
                MATCH (s:SourceArtifact {source_id: $source_id})
                MERGE (tc)-[:SUPPORTED_BY]->(s)
            """, claim_id=claim_id, source_id=source_id)

        write_audit_event(
            driver, action_type="CREATE",
            object_type="TechnicalClaim", object_id=claim_id,
            actor_id=actor_id,
            delta={"claim_type": claim_type, "claimant_type": claimant_type},
            reason=f"创建技术主张: {claim_type}",
        )
        return claim_id


def get_claims_by_construct(driver, construct_id):
    """查询某构建体的所有技术主张，附带来源。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tc)-[:SUPPORTED_BY]->(s:SourceArtifact)
            RETURN tc.claim_id AS id, tc.claim_type AS claim_type,
                   tc.claim_text AS claim_text, tc.claimant_type AS claimant_type,
                   tc.evidence_context AS evidence_context,
                   tc.claim_status AS status,
                   s.source_id AS source_id, s.title AS source_title
            ORDER BY tc.created_at DESC
        """, construct_id=construct_id)
        return [dict(record) for record in result]


def detect_claim_evidence_gaps(driver, construct_id):
    """
    检测某构建体的主张-证据缺口。

    规则：
        - 若某主张没有同类型 result → high 严重度
        - 若 result 方向非 positive → medium 严重度
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            WITH ec, COLLECT(DISTINCT tc) AS claims, COLLECT(DISTINCT tr) AS results
            RETURN ec.construct_id AS construct_id, ec.public_name AS name,
                   SIZE(claims) AS total_claims, SIZE(results) AS total_results,
                   claims, results
        """, construct_id=construct_id)
        record = result.single()
        if not record:
            return {"error": f"构建体 {construct_id} 不存在"}

        claims = [dict(c) for c in record['claims']]
        results = [dict(r) for r in record['results']]
        gaps = []
        for claim in claims:
            claim_type = claim.get('claim_type')
            matching_results = [r for r in results if r.get('result_type') == claim_type]
            if not matching_results:
                # 无同类型结果 → 高严重度缺口
                gaps.append({
                    "claim_id": claim['claim_id'],
                    "claimed_capability": claim.get('claim_text', '')[:50],
                    "available_results": [],
                    "missing_validation_stage": claim.get('evidence_context', 'unknown'),
                    "gap_severity": "high",
                })
            else:
                for result in matching_results:
                    if result.get('outcome_direction') not in ['positive', None]:
                        # 结果方向非正向 → 中等严重度
                        gaps.append({
                            "claim_id": claim['claim_id'],
                            "claimed_capability": claim.get('claim_text', '')[:50],
                            "available_results": [result.get('result_type')],
                            "missing_validation_stage": result.get('study_context', 'unknown'),
                            "gap_severity": "medium",
                        })

        return {
            "construct_id": construct_id,
            "construct_name": record['name'],
            "total_claims": record['total_claims'],
            "total_results": record['total_results'],
            "gaps": gaps,
            "has_gap": len(gaps) > 0,
        }


# ==================================================================
# Part 2: DeepSeek 候选抽取 (原 extract_service.py 全部)
# ==================================================================
import json
import re
from datetime import datetime
from typing import Any

from src.shared.deepseek_client import get_deepseek_client, repair_json, chat_json


# 抽取 schema 版本
EXTRACTION_SCHEMA_VERSION = "v1.0"

# 受控词表（用于校验 LLM 输出）
ALLOWED_CLAIM_TYPES = {"efficacy", "host_range", "safety", "manufacturability", "mechanism"}
ALLOWED_RESULT_TYPES = {"host_range", "lysis", "biofilm", "safety", "in_vivo", "computational"}
ALLOWED_STUDY_CONTEXTS = {"in_vitro", "animal", "clinical", "computational"}
ALLOWED_OUTCOME_DIRECTIONS = {"positive", "negative", "mixed", "neutral"}
ALLOWED_CLAIMANT_TYPES = {"publication", "patent", "company", "investigator"}
ALLOWED_CONSTRUCT_STATUSES = {"proposed", "built", "in_vitro_tested", "in_vivo_tested", "clinical"}
ALLOWED_STRATEGY_TYPES = {
    "host_range_expansion", "tail_fiber_engineering", "receptor_binding_engineering",
    "lysis_enhancement", "lysogeny_removal", "biofilm_disruption", "payload_delivery",
    "anti_resistance_payload", "anti_virulence_payload", "immune_modulation",
    "phage_display", "genome_minimization", "manufacturability_optimization",
    "stability_optimization", "delivery_optimization", "other",
}

# 候选类型 → (Neo4j label, id 属性名)
CANDIDATE_TYPES = {
    "claim":     {"label": "TechnicalClaim",           "id_prop": "claim_id"},
    "result":    {"label": "TechnicalResult",          "id_prop": "result_id"},
    "construct": {"label": "EngineeredPhageConstruct", "id_prop": "construct_id"},
    "strategy":  {"label": "EngineeringStrategy",      "id_prop": "strategy_id"},
}


# 系统提示词：严格禁止推测，只输出 JSON
_SYSTEM_PROMPT = """你是噬菌体技术情报抽取助手。你的任务是从给定的论文、专利或公司公告文本中，抽取"技术候选对象"。

严格要求：
1. 只抽取文本中明确出现的信息。禁止推测、禁止补充背景知识。
2. 所有输出均为"候选对象"，不代表已核实事实。
3. 输出必须是严格的 JSON，不要任何 Markdown 代码块标记。
4. 保留原文位置：每个对象必须带 exact_quote（原文片段，≤200 字）和 char_offset。
5. 无法确定的字段填空字符串、空数组或 null，不要瞎编。
6. 输出规模控制：candidate_claims ≤ 30，candidate_constructs ≤ 10，
   candidate_strategies ≤ 10，candidate_results ≤ 20。
7. 输出语言与原文保持一致。"""


# 用户提示词模板
_USER_TEMPLATE = """来源 URL：{url}
来源标题：{title}
来源类型：{source_type}

正文（前 {max_chars} 字）：
{content}

请严格按以下 JSON 结构输出抽取结果：

{{
  "candidate_strategies": [],
  "candidate_constructs": [],
  "candidate_claims": [],
  "candidate_results": []
}}

规则：
- 每项字段：strategy_type/claim_type/result_type/study_context/outcome_direction/claimant_type
  必须从对应枚举中选，否则该条不输出。
- exact_quote 必须是正文中真实出现的片段。
- 只输出 JSON，不要任何解释文字。"""


def _validate_and_normalize(candidates: dict) -> dict:
    """
    对 LLM 输出的候选对象做受控词表校验与字段归一化。

    非法枚举值的条目会被丢弃；数值字段做类型转换，失败则置 None。
    """
    def _norm_enum(v, allowed):
        if v is None:
            return None
        v = str(v).strip().lower()
        return v if v in allowed else None

    # 策略
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

    # 构建体
    constructs = []
    for c in candidates.get("candidate_constructs", []) or []:
        status = _norm_enum(c.get("construct_status"), ALLOWED_CONSTRUCT_STATUSES) or "proposed"
        strategy_refs = [x for x in (c.get("strategy_refs") or []) if x in ALLOWED_STRATEGY_TYPES]
        constructs.append({
            "public_name": (c.get("public_name") or "").strip()[:120],
            "construct_code": (c.get("construct_code") or "").strip()[:120],
            "parent_phage": (c.get("parent_phage") or "").strip()[:120],
            "construct_status": status,
            "target_pathogen_text": (c.get("target_pathogen_text") or "").strip()[:200],
            "intended_effects": [str(x).strip()[:80] for x in (c.get("intended_effects") or []) if x][:20],
            "strategy_refs": strategy_refs,
            "exact_quote": (c.get("exact_quote") or "").strip()[:400],
            "char_offset": c.get("char_offset"),
        })

    # 主张
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
            "claim_type": ct, "claim_text": claim_text,
            "exact_quote": (cl.get("exact_quote") or "").strip()[:400],
            "char_offset": cl.get("char_offset"),
            "claimant_type": claimant, "evidence_context": ctx,
            "construct_ref": (cl.get("construct_ref") or "").strip()[:120],
            "strategy_ref": (cl.get("strategy_ref") or "").strip()[:80],
        })

    # 结果
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
            "result_type": rt, "study_context": sc, "outcome_direction": od,
            "metric_name": (r.get("metric_name") or "").strip()[:80],
            "metric_value": mv, "metric_unit": (r.get("metric_unit") or "").strip()[:30],
            "sample_size": ss, "comparator": (r.get("comparator") or "").strip()[:80],
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


def extract_technical_candidates(driver: Driver, source_artifact_id: str,
                                 source_text: str,
                                 extraction_schema_version: str = EXTRACTION_SCHEMA_VERSION,
                                 actor_id: str = "deepseek_extractor") -> Dict[str, Any]:
    """
    调用 DeepSeek 从来源文本抽取技术候选对象（不落库）。

    Args:
        source_artifact_id: 来源 ID
        source_text: 正文（前 8000 字送入模型）
        extraction_schema_version: schema 版本
        actor_id: 操作者

    Returns:
        Dict: {source_artifact_id, schema_version, extracted_at, candidates, stats}
    """
    if not source_text or not source_text.strip():
        raise ValueError("source_text 为空，无法抽取")

    # 查询来源基础信息，用于填充 prompt
    with driver.session() as s:
        rec = s.run("""
            MATCH (src:SourceArtifact {source_id: $sid})
            RETURN src.source_id AS sid, src.title AS title,
                   src.url AS url, src.source_type AS source_type
        """, sid=source_artifact_id).single()
    if not rec:
        raise ValueError(f"SourceArtifact {source_artifact_id} 不存在")

    # 调用 LLM
    user_prompt = _USER_TEMPLATE.format(
        url=rec["url"] or "", title=rec["title"] or "",
        source_type=rec["source_type"] or "unknown",
        max_chars=8000, content=source_text[:8000],
    )
    raw = chat_json(_SYSTEM_PROMPT, user_prompt)
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
        driver, action_type="CREATE",
        object_type="TechnicalCandidateExtraction",
        object_id=f"EXT:{uuid.uuid4().hex[:8].upper()}",
        actor_id=actor_id,
        delta={"source_artifact_id": source_artifact_id,
               "schema_version": extraction_schema_version, **stats},
        reason=f"DeepSeek 抽取技术候选对象：{stats}",
    )
    return {
        "source_artifact_id": source_artifact_id,
        "schema_version": extraction_schema_version,
        "extracted_at": datetime.now().isoformat(),
        "candidates": normalized,
        "stats": stats,
    }


def _gen_claim_id():
    """内部：生成 claim ID。"""
    return f"ENG:CLAIM:{uuid.uuid4().hex[:8].upper()}"


def _gen_result_id():
    """内部：生成 result ID。"""
    return f"ENG:RESULT:{uuid.uuid4().hex[:8].upper()}"


def _gen_construct_id():
    """内部：生成 construct ID。"""
    return f"ENG:CONST:{uuid.uuid4().hex[:8].upper()}"


def _gen_strategy_id():
    """内部：生成 strategy ID。"""
    return f"ENG:STRAT:{uuid.uuid4().hex[:8].upper()}"


def persist_candidates(driver: Driver, extraction_result: Dict[str, Any],
                       actor_id: str = "deepseek_extractor") -> Dict[str, List[str]]:
    """
    把抽取到的候选对象落库为图谱节点，并自动创建 Review 记录。

    落库策略：
        - 策略：按 strategy_type 幂等；已存在则复用，不覆盖
        - 构建体：按 public_name 幂等
        - 主张：按 claim_text 幂等
        - 结果：每次创建新节点

    所有新节点 review_status = 'pending'，并生成 Review（technical_intelligence_review）。

    Args:
        extraction_result: extract_technical_candidates 的返回值
        actor_id: 操作者

    Returns:
        Dict: {strategy_ids, construct_ids, claim_ids, result_ids}
    """
    sid = extraction_result["source_artifact_id"]
    schema_version = extraction_result.get("schema_version", EXTRACTION_SCHEMA_VERSION)
    cand = extraction_result["candidates"]
    out = {"strategy_ids": [], "construct_ids": [], "claim_ids": [], "result_ids": []}
    strategy_type_to_id = {}      # 本轮抽取中 strategy_type → strategy_id
    construct_name_to_id = {}     # 本轮抽取中 public_name → construct_id

    with driver.session() as s:
        # 校验来源存在
        ok = s.run("MATCH (src:SourceArtifact {source_id: $sid}) RETURN src.source_id AS x",
                   sid=sid).single()
        if not ok:
            raise ValueError(f"SourceArtifact {sid} 不存在")

        # ---------- 策略 ----------
        for st in cand.get("candidate_strategies", []):
            stype = st["strategy_type"]
            # 幂等：按 strategy_type 复用已有节点
            existing = s.run("""
                MATCH (es:EngineeringStrategy {strategy_type: $st})
                RETURN es.strategy_id AS sid LIMIT 1
            """, st=stype).single()
            if existing:
                strategy_type_to_id[stype] = existing["sid"]
                s.run("""
                    MATCH (es:EngineeringStrategy {strategy_id: $eid})
                    MATCH (src:SourceArtifact {source_id: $sid})
                    MERGE (es)-[:SUPPORTED_BY]->(src)
                """, eid=existing["sid"], sid=sid)
                if existing["sid"] not in out["strategy_ids"]:
                    out["strategy_ids"].append(existing["sid"])
                continue

            # 创建新策略
            str_id = _gen_strategy_id()
            s.run("""
                CREATE (es:EngineeringStrategy {
                    strategy_id: $eid, strategy_type: $stype,
                    description: $desc, evidence_maturity: 'conceptual',
                    review_status: 'pending', extracted_by: 'deepseek',
                    extraction_schema_version: $ver, source_artifact_id: $sid,
                    exact_quote: $quote, char_offset: $offset,
                    created_at: datetime(), updated_at: datetime()
                })
            """, eid=str_id, stype=stype, desc=st["description"] or "",
                 ver=schema_version, sid=sid, quote=st["exact_quote"] or "",
                 offset=st["char_offset"])
            # SUPPORTED_BY 来源
            s.run("""
                MATCH (es:EngineeringStrategy {strategy_id: $eid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (es)-[:SUPPORTED_BY]->(src)
            """, eid=str_id, sid=sid)
            # 自动创建 Review
            s.run("""
                MATCH (es:EngineeringStrategy {strategy_id: $eid})
                CREATE (r:Review {
                    review_id: $rid, review_type: 'technical_intelligence_review',
                    target_object_type: 'EngineeringStrategy',
                    target_object_id: $eid, reviewer_id: 'pending',
                    decision: 'pending', comment: '', created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(es)
            """, eid=str_id, rid=f"REV-{uuid.uuid4().hex[:8].upper()}")
            strategy_type_to_id[stype] = str_id
            out["strategy_ids"].append(str_id)

        # ---------- 构建体 ----------
        for c in cand.get("candidate_constructs", []):
            name = c.get("public_name") or c.get("construct_code")
            if not name:
                continue
            # 幂等：按 public_name 复用
            existing = s.run("""
                MATCH (ec:EngineeredPhageConstruct {public_name: $n})
                RETURN ec.construct_id AS cid LIMIT 1
            """, n=name).single()
            if existing:
                construct_name_to_id[name] = existing["cid"]
                s.run("""
                    MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                    MATCH (src:SourceArtifact {source_id: $sid})
                    MERGE (ec)-[:REPORTED_IN]->(src)
                """, cid=existing["cid"], sid=sid)
                if existing["cid"] not in out["construct_ids"]:
                    out["construct_ids"].append(existing["cid"])
                continue

            # 创建新构建体
            cid = _gen_construct_id()
            s.run("""
                CREATE (ec:EngineeredPhageConstruct {
                    construct_id: $cid, public_name: $name,
                    construct_code: $code, construct_status: $status,
                    intended_effects: $effects,
                    target_pathogen_text: $tpt,
                    review_status: 'pending', extracted_by: 'deepseek',
                    extraction_schema_version: $ver, source_artifact_id: $sid,
                    exact_quote: $quote, char_offset: $offset,
                    first_public_date: null,
                    created_at: datetime(), updated_at: datetime()
                })
            """, cid=cid, name=name, code=c.get("construct_code") or "",
                 status=c.get("construct_status") or "proposed",
                 effects=c.get("intended_effects") or [],
                 tpt=c.get("target_pathogen_text") or "",
                 ver=schema_version, sid=sid,
                 quote=c.get("exact_quote") or "",
                 offset=c.get("char_offset"))
            # REPORTED_IN 来源
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (ec)-[:REPORTED_IN]->(src)
            """, cid=cid, sid=sid)
            # IMPLEMENTS 策略（由 strategy_refs 映射）
            for st_ref in c.get("strategy_refs", []):
                st_id = strategy_type_to_id.get(st_ref)
                if not st_id:
                    continue
                s.run("""
                    MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                    MATCH (es:EngineeringStrategy {strategy_id: $sid})
                    MERGE (ec)-[:IMPLEMENTS]->(es)
                """, cid=cid, sid=st_id)
            # DERIVED_FROM 亲本噬菌体（如果图谱中能匹配到）
            if c.get("parent_phage"):
                s.run("""
                    MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                    MATCH (ph:Phage)
                    WHERE ph.name = $pname OR ph.phage_id = $pname
                    MERGE (ec)-[:DERIVED_FROM]->(ph)
                """, cid=cid, pname=c["parent_phage"])
            # 自动创建 Review
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                CREATE (r:Review {
                    review_id: $rid, review_type: 'technical_intelligence_review',
                    target_object_type: 'EngineeredPhageConstruct',
                    target_object_id: $cid, reviewer_id: 'pending',
                    decision: 'pending', comment: '', created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(ec)
            """, cid=cid, rid=f"REV-{uuid.uuid4().hex[:8].upper()}")
            construct_name_to_id[name] = cid
            out["construct_ids"].append(cid)

        # ---------- 主张 ----------
        for cl in cand.get("candidate_claims", []):
            # 幂等：claim_text 相同跳过
            existing = s.run("""
                MATCH (tc:TechnicalClaim {claim_text: $t})
                RETURN tc.claim_id AS cid LIMIT 1
            """, t=cl["claim_text"]).single()
            if existing:
                continue
            clm_id = _gen_claim_id()
            s.run("""
                CREATE (tc:TechnicalClaim {
                    claim_id: $cid, claim_type: $ctype, claim_text: $text,
                    exact_quote: $quote, char_offset: $offset,
                    claimant_type: $claimant, evidence_context: $ctx,
                    claim_status: 'asserted', confidence: 'medium',
                    review_status: 'pending', extracted_by: 'deepseek',
                    extraction_schema_version: $ver, source_artifact_id: $sid,
                    created_at: datetime(), updated_at: datetime()
                })
            """, cid=clm_id, ctype=cl["claim_type"], text=cl["claim_text"],
                 quote=cl["exact_quote"] or "", offset=cl["char_offset"],
                 claimant=cl["claimant_type"], ctx=cl.get("evidence_context"),
                 ver=schema_version, sid=sid)
            # SUPPORTED_BY 来源
            s.run("""
                MATCH (tc:TechnicalClaim {claim_id: $cid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (tc)-[:SUPPORTED_BY]->(src)
            """, cid=clm_id, sid=sid)
            # CLAIMS_ABOUT 构建体
            if cl.get("construct_ref"):
                c_id = construct_name_to_id.get(cl["construct_ref"])
                if c_id:
                    s.run("""
                        MATCH (tc:TechnicalClaim {claim_id: $cid})
                        MATCH (ec:EngineeredPhageConstruct {construct_id: $eid})
                        MERGE (tc)-[:CLAIMS_ABOUT]->(ec)
                    """, cid=clm_id, eid=c_id)
            # CLAIMS_ABOUT 策略
            if cl.get("strategy_ref"):
                st_id = strategy_type_to_id.get(cl["strategy_ref"])
                if st_id:
                    s.run("""
                        MATCH (tc:TechnicalClaim {claim_id: $cid})
                        MATCH (es:EngineeringStrategy {strategy_id: $sid})
                        MERGE (tc)-[:CLAIMS_ABOUT]->(es)
                    """, cid=clm_id, sid=st_id)
            # 自动 Review
            s.run("""
                MATCH (tc:TechnicalClaim {claim_id: $cid})
                CREATE (r:Review {
                    review_id: $rid, review_type: 'technical_intelligence_review',
                    target_object_type: 'TechnicalClaim',
                    target_object_id: $cid, reviewer_id: 'pending',
                    decision: 'pending', comment: '', created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(tc)
            """, cid=clm_id, rid=f"REV-{uuid.uuid4().hex[:8].upper()}")
            out["claim_ids"].append(clm_id)

        # ---------- 结果 ----------
        for r_ in cand.get("candidate_results", []):
            res_id = _gen_result_id()
            s.run("""
                CREATE (tr:TechnicalResult {
                    result_id: $rid, result_type: $rtype,
                    study_context: $ctx, outcome_direction: $od,
                    metric_name: $mn, metric_value: $mv, metric_unit: $mu,
                    comparator: $cmp, sample_size: $ss,
                    limitation_summary: $lim,
                    reproducibility_status: 'single_source',
                    review_status: 'pending', extracted_by: 'deepseek',
                    extraction_schema_version: $ver, source_artifact_id: $sid,
                    exact_quote: $quote, char_offset: $offset,
                    created_at: datetime(), updated_at: datetime()
                })
            """, rid=res_id, rtype=r_["result_type"], ctx=r_["study_context"],
                 od=r_.get("outcome_direction"),
                 mn=r_.get("metric_name") or "", mv=r_.get("metric_value"),
                 mu=r_.get("metric_unit") or "", cmp=r_.get("comparator") or "",
                 ss=r_.get("sample_size"), lim=r_.get("limitation_summary") or "",
                 ver=schema_version, sid=sid,
                 quote=r_.get("exact_quote") or "",
                 offset=r_.get("char_offset"))
            # REPORTED_IN 来源
            s.run("""
                MATCH (tr:TechnicalResult {result_id: $rid})
                MATCH (src:SourceArtifact {source_id: $sid})
                MERGE (tr)-[:REPORTED_IN]->(src)
            """, rid=res_id, sid=sid)
            # RESULT_FOR 构建体
            if r_.get("construct_ref"):
                c_id = construct_name_to_id.get(r_["construct_ref"])
                if c_id:
                    s.run("""
                        MATCH (tr:TechnicalResult {result_id: $rid})
                        MATCH (ec:EngineeredPhageConstruct {construct_id: $eid})
                        MERGE (tr)-[:RESULT_FOR]->(ec)
                    """, rid=res_id, eid=c_id)
            # 自动 Review
            s.run("""
                MATCH (tr:TechnicalResult {result_id: $rid})
                CREATE (r:Review {
                    review_id: $rid2, review_type: 'technical_intelligence_review',
                    target_object_type: 'TechnicalResult',
                    target_object_id: $rid, reviewer_id: 'pending',
                    decision: 'pending', comment: '', created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(tr)
            """, rid=res_id, rid2=f"REV-{uuid.uuid4().hex[:8].upper()}")
            out["result_ids"].append(res_id)

    # 汇总审计
    write_audit_event(
        driver, action_type="CREATE",
        object_type="TechnicalCandidatePersist",
        object_id=f"PERSIST:{uuid.uuid4().hex[:8].upper()}",
        actor_id=actor_id,
        delta={"source_artifact_id": sid, **{k: v for k, v in out.items()}},
        reason=f"落库技术候选对象：{ {k: len(v) for k, v in out.items()} }",
    )
    return out


def list_pending_candidates(driver, limit=100):
    """
    列出所有待审核的 DeepSeek 抽取候选对象（策略 / 构建体 / 主张 / 结果）。
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


def approve_candidate(driver, candidate_type, node_id, reviewer_id, comment=""):
    """
    审核通过候选对象：
        - 更新 Review 决策为 approved
        - 更新节点的 review_status 为 approved
    """
    if candidate_type not in CANDIDATE_TYPES:
        raise ValueError(f"candidate_type 必须是 {list(CANDIDATE_TYPES)} 之一")
    label = CANDIDATE_TYPES[candidate_type]["label"]
    id_prop = CANDIDATE_TYPES[candidate_type]["id_prop"]

    with driver.session() as s:
        check = s.run(f"MATCH (n:{label} {{`{id_prop}`: $oid}}) RETURN n", oid=node_id).single()
        if not check:
            raise ValueError(f"{label} {node_id} 不存在")
        # 更新 Review
        s.run(f"""
            MATCH (r:Review)-[:REVIEWS]->(n:{label} {{`{id_prop}`: $oid}})
            WHERE r.reviewer_id = 'pending' OR r.decision = 'pending'
            SET r.decision = 'approved', r.reviewer_id = $rid,
                r.comment = $c, r.reviewed_at = datetime()
        """, oid=node_id, rid=reviewer_id, c=comment)
        # 更新节点状态
        s.run(f"""
            MATCH (n:{label} {{`{id_prop}`: $oid}})
            SET n.review_status = 'approved', n.updated_at = datetime()
        """, oid=node_id)

    write_audit_event(
        driver, action_type="REVIEW_APPROVE",
        object_type=label, object_id=node_id, actor_id=reviewer_id,
        delta={"review_status": "approved"},
        reason=comment or f"审核通过 {candidate_type} {node_id}",
    )
    return node_id


def reject_candidate(driver, candidate_type, node_id, reviewer_id, comment=""):
    """
    审核拒绝候选对象：
        - 更新 Review 决策为 rejected
        - 更新节点的 review_status 为 rejected
    """
    if candidate_type not in CANDIDATE_TYPES:
        raise ValueError(f"candidate_type 必须是 {list(CANDIDATE_TYPES)} 之一")
    label = CANDIDATE_TYPES[candidate_type]["label"]
    id_prop = CANDIDATE_TYPES[candidate_type]["id_prop"]

    with driver.session() as s:
        check = s.run(f"MATCH (n:{label} {{`{id_prop}`: $oid}}) RETURN n", oid=node_id).single()
        if not check:
            raise ValueError(f"{label} {node_id} 不存在")
        s.run(f"""
            MATCH (r:Review)-[:REVIEWS]->(n:{label} {{`{id_prop}`: $oid}})
            WHERE r.reviewer_id = 'pending' OR r.decision = 'pending'
            SET r.decision = 'rejected', r.reviewer_id = $rid,
                r.comment = $c, r.reviewed_at = datetime()
        """, oid=node_id, rid=reviewer_id, c=comment)
        s.run(f"""
            MATCH (n:{label} {{`{id_prop}`: $oid}})
            SET n.review_status = 'rejected', n.updated_at = datetime()
        """, oid=node_id)

    write_audit_event(
        driver, action_type="REVIEW_REJECT",
        object_type=label, object_id=node_id, actor_id=reviewer_id,
        delta={"review_status": "rejected"},
        reason=comment or f"审核拒绝 {candidate_type} {node_id}",
    )
    return node_id


def extract_and_persist(driver, source_artifact_id, source_text,
                        actor_id="deepseek_extractor"):
    """
    一站式入口：抽取 + 落库。
    """
    extraction = extract_technical_candidates(
        driver, source_artifact_id, source_text, actor_id=actor_id)
    ids = persist_candidates(driver, extraction, actor_id=actor_id)
    return {"extraction": extraction, "persisted_ids": ids}