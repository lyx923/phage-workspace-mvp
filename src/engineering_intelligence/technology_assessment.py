# src/engineering_intelligence/technology_assessment.py
"""
TechnologyAssessment / ClaimConflict / IPMapping
合并服务（PRD 9.6 / 14 / 11）

包含三个部分：
    Part 1: TechnologyAssessment —— 技术评估
    Part 2: ClaimConflict        —— 主张 / 结果冲突检测
    Part 3: IPMapping            —— 专利-主张映射

边界原则：
    - 冲突检测只标记矛盾，不做真伪判断
    - IP 映射基于文本相似度，不代表侵权或自由实施判断
"""

# ==================================================================
# Part 1: TechnologyAssessment (原 technology_assessment.py)
# ==================================================================
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event


# 受控词表
EVIDENCE_MATURITY_LEVELS = ["conceptual", "in_vitro", "in_vivo", "clinical"]
RELEVANCE_LEVELS = ["high", "medium", "low", "unknown"]
RISK_LEVELS = ["high", "medium", "low", "unknown"]

# subject_type → (label, id 属性名)
SUBJECT_MAP = {
    "construct": ("EngineeredPhageConstruct", "construct_id"),
    "strategy":  ("EngineeringStrategy",      "strategy_id"),
    "claim":     ("TechnicalClaim",           "claim_id"),
}


def generate_assessment_id() -> str:
    """生成技术评估 ID（格式：ENG:ASSESS:XXXXXXXX）。"""
    return f"ENG:ASSESS:{uuid.uuid4().hex[:8].upper()}"


def create_technology_assessment(
    driver: Driver, subject_type: str, subject_id: str,
    evidence_maturity: str = "conceptual",
    technical_relevance: str = "medium",
    translational_potential: str = "unknown",
    manufacturability_risk: str = "unknown",
    safety_uncertainty: str = "unknown",
    ip_relevance: str = "unknown",
    internal_capability_gap: str = "unknown",
    assessment_summary: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    创建技术评估。

    - 校验 subject 存在
    - 建立 (评估)-[:ASSESSES]->(subject)
    - 若 subject_type 为 claim，额外建立 (claim)-[:EVALUATED_BY]->(评估)

    Args:
        subject_type: construct / strategy / claim
        subject_id: 被评估对象 ID
        evidence_maturity: 证据成熟度
        technical_relevance: 技术相关性
        translational_potential: 转化潜力
        manufacturability_risk: 可制造性风险
        safety_uncertainty: 安全性不确定
        ip_relevance: IP 相关性
        internal_capability_gap: 内部能力缺口
        assessment_summary: 评估摘要
        actor_id: 操作者

    Returns:
        str: assessment_id
    """
    if evidence_maturity not in EVIDENCE_MATURITY_LEVELS:
        raise ValueError(f"证据成熟度必须是以下之一: {EVIDENCE_MATURITY_LEVELS}")
    if technical_relevance not in RELEVANCE_LEVELS:
        raise ValueError(f"技术相关性必须是以下之一: {RELEVANCE_LEVELS}")
    if subject_type not in SUBJECT_MAP:
        raise ValueError(f"subject_type 必须是 {list(SUBJECT_MAP.keys())} 之一")

    label, id_prop = SUBJECT_MAP[subject_type]
    assessment_id = generate_assessment_id()

    with driver.session() as session:
        # 校验 subject 存在
        check = session.run(
            f"MATCH (n:{label} {{`{id_prop}`: $sid}}) RETURN n LIMIT 1",
            sid=subject_id,
        ).single()
        if not check:
            raise ValueError(f"{subject_type} {subject_id} 不存在")

        # 创建评估节点
        session.run("""
            CREATE (ta:TechnologyAssessment {
                technology_assessment_id: $assessment_id,
                subject_type: $subject_type, subject_id: $subject_id,
                evidence_maturity: $evidence_maturity,
                technical_relevance: $technical_relevance,
                translational_potential: $translational_potential,
                manufacturability_risk: $manufacturability_risk,
                safety_uncertainty: $safety_uncertainty,
                ip_relevance: $ip_relevance,
                internal_capability_gap: $internal_capability_gap,
                assessment_summary: $assessment_summary,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
        """, assessment_id=assessment_id, subject_type=subject_type,
             subject_id=subject_id, evidence_maturity=evidence_maturity,
             technical_relevance=technical_relevance,
             translational_potential=translational_potential,
             manufacturability_risk=manufacturability_risk,
             safety_uncertainty=safety_uncertainty,
             ip_relevance=ip_relevance,
             internal_capability_gap=internal_capability_gap,
             assessment_summary=assessment_summary)

        # ASSESSES 关系
        session.run(f"""
            MATCH (ta:TechnologyAssessment {{technology_assessment_id: $assessment_id}})
            MATCH (n:{label} {{`{id_prop}`: $subject_id}})
            MERGE (ta)-[:ASSESSES]->(n)
        """, assessment_id=assessment_id, subject_id=subject_id)

        # claim 特有：EVALUATED_BY
        if subject_type == "claim":
            session.run("""
                MATCH (ta:TechnologyAssessment {technology_assessment_id: $assessment_id})
                MATCH (tc:TechnicalClaim {claim_id: $subject_id})
                MERGE (tc)-[:EVALUATED_BY]->(ta)
            """, assessment_id=assessment_id, subject_id=subject_id)

        write_audit_event(
            driver, action_type="CREATE",
            object_type="TechnologyAssessment", object_id=assessment_id,
            actor_id=actor_id,
            delta={"subject_type": subject_type, "subject_id": subject_id,
                   "evidence_maturity": evidence_maturity,
                   "technical_relevance": technical_relevance},
            reason=f"创建技术评估: {subject_type} {subject_id}",
        )
        return assessment_id


def get_assessment_for_subject(driver, subject_type, subject_id):
    """查询某对象的最新一条技术评估。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (ta:TechnologyAssessment {subject_type: $subject_type, subject_id: $subject_id})
            RETURN ta.technology_assessment_id AS id,
                   ta.evidence_maturity AS evidence_maturity,
                   ta.technical_relevance AS technical_relevance,
                   ta.translational_potential AS translational_potential,
                   ta.manufacturability_risk AS manufacturability_risk,
                   ta.safety_uncertainty AS safety_uncertainty,
                   ta.ip_relevance AS ip_relevance,
                   ta.internal_capability_gap AS internal_capability_gap,
                   ta.assessment_summary AS summary,
                   ta.review_status AS review_status,
                   ta.created_at AS created_at
            ORDER BY ta.created_at DESC LIMIT 1
        """, subject_type=subject_type, subject_id=subject_id)
        record = result.single()
        return dict(record) if record else None


def get_assessments_by_strategy(driver, strategy_type):
    """
    查询某策略类型下的所有评估（策略本身 + 其下构建体）。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (es:EngineeringStrategy {strategy_type: $strategy_type})
            OPTIONAL MATCH (es)<-[:IMPLEMENTS]-(ec:EngineeredPhageConstruct)
            OPTIONAL MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(es)
            OPTIONAL MATCH (ta2:TechnologyAssessment)-[:ASSESSES]->(ec)
            WITH es, ec, ta, ta2
            RETURN es.strategy_id AS strategy_id,
                   es.strategy_type AS strategy_type,
                   ec.construct_id AS construct_id,
                   ec.public_name AS construct_name,
                   ta.technology_assessment_id AS strategy_assessment_id,
                   ta.evidence_maturity AS strategy_maturity,
                   ta.technical_relevance AS strategy_relevance,
                   ta2.technology_assessment_id AS construct_assessment_id,
                   ta2.evidence_maturity AS construct_maturity,
                   ta2.technical_relevance AS construct_relevance
            ORDER BY es.strategy_type
        """, strategy_type=strategy_type)
        return [dict(record) for record in result]


def get_assessments_for_claim(driver, claim_id):
    """查询某主张的所有技术评估。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (ta:TechnologyAssessment {subject_type: 'claim', subject_id: $cid})
            RETURN ta.technology_assessment_id AS assessment_id,
                   ta.evidence_maturity AS evidence_maturity,
                   ta.technical_relevance AS technical_relevance,
                   ta.translational_potential AS translational_potential,
                   ta.manufacturability_risk AS manufacturability_risk,
                   ta.safety_uncertainty AS safety_uncertainty,
                   ta.ip_relevance AS ip_relevance,
                   ta.internal_capability_gap AS internal_capability_gap,
                   ta.assessment_summary AS summary,
                   ta.review_status AS review_status,
                   ta.created_at AS created_at
            ORDER BY ta.created_at DESC
        """, cid=claim_id)
        return [dict(record) for record in result]


def backfill_claim_evaluated_by(driver, actor_id="backfill"):
    """
    回填 EVALUATED_BY 关系：
    从 (评估)-ASSESSES->(主张) 推导 (主张)-EVALUATED_BY->(评估)。
    """
    created = 0
    details = []
    with driver.session() as session:
        rows = list(session.run("""
            MATCH (ta:TechnologyAssessment)-[:ASSESSES]->(tc:TechnicalClaim)
            WHERE ta.subject_type = 'claim'
              AND NOT (tc)-[:EVALUATED_BY]->(ta)
            RETURN ta.technology_assessment_id AS taid, tc.claim_id AS cid
        """))
        for r in rows:
            session.run("""
                MATCH (ta:TechnologyAssessment {technology_assessment_id: $taid})
                MATCH (tc:TechnicalClaim {claim_id: $cid})
                MERGE (tc)-[:EVALUATED_BY]->(ta)
            """, taid=r["taid"], cid=r["cid"])
            created += 1
            details.append({"assessment_id": r["taid"], "claim_id": r["cid"]})

    if created > 0:
        write_audit_event(
            driver, action_type="LINK_CREATE",
            object_type="TechnicalClaim", object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_evaluated_by": created, "details": details},
            reason=f"回填 EVALUATED_BY 关系：{created} 条",
        )
    return {"created": created, "details": details}


def suggest_assessment_from_evidence(driver, construct_id):
    """
    基于现有证据自动建议评估参数（成熟度 / 相关性）。

    规则：
        证据上下文含 clinical    → 成熟度 clinical
        含 in_vivo              → in_vivo
        含 in_vitro             → in_vitro
        只有结果但无上下文        → in_vitro
        只有主张                 → conceptual
        否则                     → conceptual

        有 positive 结果          → 相关性 high
        有 mixed 结果             → medium
        否则                     → medium

    仅作为建议，最终须专家确认。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            RETURN ec.construct_id AS id, ec.public_name AS name,
                   COLLECT(DISTINCT tc.claim_type) AS claim_types,
                   COLLECT(DISTINCT tr.result_type) AS result_types,
                   COLLECT(DISTINCT tr.study_context) AS study_contexts,
                   COLLECT(DISTINCT tr.outcome_direction) AS outcomes
        """, construct_id=construct_id)
        record = result.single()
        if not record:
            return {"error": f"构建体 {construct_id} 不存在"}
        data = dict(record)
        study_contexts = data.get('study_contexts', [])
        # 成熟度推断
        if 'clinical' in study_contexts:
            evidence_maturity = 'clinical'
        elif 'in_vivo' in study_contexts:
            evidence_maturity = 'in_vivo'
        elif 'in_vitro' in study_contexts:
            evidence_maturity = 'in_vitro'
        elif data.get('result_types'):
            evidence_maturity = 'in_vitro'
        elif data.get('claim_types'):
            evidence_maturity = 'conceptual'
        else:
            evidence_maturity = 'conceptual'

        # 相关性推断
        outcomes = data.get('outcomes', [])
        if 'positive' in outcomes:
            technical_relevance = 'high'
        elif 'mixed' in outcomes:
            technical_relevance = 'medium'
        else:
            technical_relevance = 'medium'

        return {
            "construct_id": construct_id,
            "construct_name": data.get('name'),
            "suggested_evidence_maturity": evidence_maturity,
            "suggested_technical_relevance": technical_relevance,
            "has_claims": len(data.get('claim_types', [])) > 0,
            "has_results": len(data.get('result_types', [])) > 0,
            "study_contexts": study_contexts, "outcomes": outcomes,
            "note": "此为基于现有证据的自动建议，需专家审核确认",
        }


# ==================================================================
# Part 2: ClaimConflict
# ==================================================================

def _find_claim_status_conflicts(driver, construct_id=None):
    """
    内部：查找同一构建体下同类主张的状态冲突
    （一个 supported + 一个 contradicted）。
    """
    where_clause = "WHERE ec.construct_id = $cid" if construct_id else ""
    params = {"cid": construct_id} if construct_id else {}
    with driver.session() as s:
        rows = list(s.run(f"""
            MATCH (tc1:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec:EngineeredPhageConstruct)
            MATCH (tc2:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            {where_clause}
            WHERE tc1.claim_id < tc2.claim_id
              AND tc1.claim_type = tc2.claim_type
              AND tc1.claim_status = 'supported'
              AND tc2.claim_status = 'contradicted'
            RETURN ec.construct_id AS construct_id,
                   ec.public_name AS construct_name,
                   tc1.claim_id AS claim_a_id, tc1.claim_text AS claim_a_text,
                   tc2.claim_id AS claim_b_id, tc2.claim_text AS claim_b_text,
                   tc1.claim_type AS claim_type
        """, **params))
    return [{"conflict_type": "claim_status_conflict",
             "construct_id": r["construct_id"], "construct_name": r["construct_name"],
             "claim_type": r["claim_type"],
             "claim_a_id": r["claim_a_id"], "claim_a_text": r["claim_a_text"][:100],
             "claim_b_id": r["claim_b_id"], "claim_b_text": r["claim_b_text"][:100]}
            for r in rows]


def _find_result_direction_conflicts(driver, construct_id=None):
    """
    内部：查找同一构建体下同类结果的方向冲突
    （一个 positive + 一个 negative）。
    """
    where_clause = "WHERE ec.construct_id = $cid" if construct_id else ""
    params = {"cid": construct_id} if construct_id else {}
    with driver.session() as s:
        rows = list(s.run(f"""
            MATCH (tr1:TechnicalResult)-[:RESULT_FOR]->(ec:EngineeredPhageConstruct)
            MATCH (tr2:TechnicalResult)-[:RESULT_FOR]->(ec)
            {where_clause}
            WHERE tr1.result_id < tr2.result_id
              AND tr1.result_type = tr2.result_type
              AND tr1.outcome_direction = 'positive'
              AND tr2.outcome_direction = 'negative'
            RETURN ec.construct_id AS construct_id,
                   ec.public_name AS construct_name,
                   tr1.result_id AS result_a_id, tr1.metric_name AS metric_a,
                   tr2.result_id AS result_b_id, tr2.metric_name AS metric_b,
                   tr1.result_type AS result_type
        """, **params))
    return [{"conflict_type": "result_direction_conflict",
             "construct_id": r["construct_id"], "construct_name": r["construct_name"],
             "result_type": r["result_type"],
             "result_a_id": r["result_a_id"], "metric_a": r["metric_a"],
             "result_b_id": r["result_b_id"], "metric_b": r["metric_b"]}
            for r in rows]


def _find_cross_construct_conflicts(driver, strategy_id=None):
    """
    内部：查找同一策略下不同构建体的结果方向冲突
    （一个 positive + 一个 negative）。
    """
    where_clause = "WHERE es.strategy_id = $sid" if strategy_id else ""
    params = {"sid": strategy_id} if strategy_id else {}
    with driver.session() as s:
        rows = list(s.run(f"""
            MATCH (ec1:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy)
            MATCH (ec2:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es)
            {where_clause}
            WHERE ec1.construct_id < ec2.construct_id
            MATCH (tr1:TechnicalResult)-[:RESULT_FOR]->(ec1)
            MATCH (tr2:TechnicalResult)-[:RESULT_FOR]->(ec2)
            WHERE tr1.result_type = tr2.result_type
              AND tr1.outcome_direction = 'positive'
              AND tr2.outcome_direction = 'negative'
            RETURN es.strategy_id AS strategy_id,
                   es.strategy_type AS strategy_type,
                   ec1.construct_id AS construct_a_id, ec1.public_name AS construct_a_name,
                   ec2.construct_id AS construct_b_id, ec2.public_name AS construct_b_name,
                   tr1.result_id AS result_a_id, tr2.result_id AS result_b_id,
                   tr1.result_type AS result_type
        """, **params))
    return [{"conflict_type": "cross_construct_conflict",
             "strategy_id": r["strategy_id"], "strategy_type": r["strategy_type"],
             "construct_a_id": r["construct_a_id"], "construct_a_name": r["construct_a_name"],
             "construct_b_id": r["construct_b_id"], "construct_b_name": r["construct_b_name"],
             "result_type": r["result_type"],
             "result_a_id": r["result_a_id"], "result_b_id": r["result_b_id"]}
            for r in rows]


def detect_conflicts(driver, construct_id=None, strategy_id=None,
                     persist=False, actor_id="conflict_detector"):
    """
    检测三类冲突。

    - claim_status_conflicts：同类主张的 status 矛盾
    - result_direction_conflicts：同类结果方向矛盾
    - cross_construct_conflicts：同一策略下不同构建体方向矛盾

    Args:
        construct_id / strategy_id: 至少提供一个
        persist: 是否把冲突持久化为 CONTRADICTS 关系
        actor_id: 操作者

    Returns:
        Dict: 冲突汇总
    """
    results = {
        "claim_status_conflicts": [],
        "result_direction_conflicts": [],
        "cross_construct_conflicts": [],
        "total_conflicts": 0,
    }
    # 若只指定 strategy_id，就跳过构建体级冲突
    if construct_id or not strategy_id:
        results["claim_status_conflicts"] = _find_claim_status_conflicts(driver, construct_id)
        results["result_direction_conflicts"] = _find_result_direction_conflicts(driver, construct_id)
    # 若只指定 construct_id，就跳过策略级冲突
    if strategy_id or not construct_id:
        results["cross_construct_conflicts"] = _find_cross_construct_conflicts(driver, strategy_id)

    results["total_conflicts"] = (
        len(results["claim_status_conflicts"])
        + len(results["result_direction_conflicts"])
        + len(results["cross_construct_conflicts"])
    )

    if persist and results["total_conflicts"] > 0:
        created = _persist_conflicts(driver, results, actor_id=actor_id)
        results["created_relations"] = created
    return results


def _persist_conflicts(driver, results, actor_id):
    """
    内部：把检测到的冲突写为 CONTRADICTS 关系（幂等）。
    """
    created = []
    with driver.session() as s:
        # 主张状态冲突
        for c in results.get("claim_status_conflicts", []):
            existing = s.run("""
                MATCH (a:TechnicalClaim {claim_id: $aid})-[r:CONTRADICTS]->(b:TechnicalClaim {claim_id: $bid})
                RETURN r.conflict_id AS cid LIMIT 1
            """, aid=c["claim_a_id"], bid=c["claim_b_id"]).single()
            if existing:
                continue
            cid = f"CONFLICT:{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (a:TechnicalClaim {claim_id: $aid})
                MATCH (b:TechnicalClaim {claim_id: $bid})
                CREATE (a)-[r:CONTRADICTS {
                    conflict_id: $cid, conflict_type: 'claim_status_conflict',
                    claim_type: $ctype, created_at: datetime()
                }]->(b)
            """, aid=c["claim_a_id"], bid=c["claim_b_id"], cid=cid, ctype=c["claim_type"])
            created.append(cid)

        # 结果方向冲突
        for c in results.get("result_direction_conflicts", []):
            existing = s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})-[r:CONTRADICTS]->(b:TechnicalResult {result_id: $bid})
                RETURN r.conflict_id AS cid LIMIT 1
            """, aid=c["result_a_id"], bid=c["result_b_id"]).single()
            if existing:
                continue
            cid = f"CONFLICT:{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})
                MATCH (b:TechnicalResult {result_id: $bid})
                CREATE (a)-[r:CONTRADICTS {
                    conflict_id: $cid, conflict_type: 'result_direction_conflict',
                    result_type: $rtype, created_at: datetime()
                }]->(b)
            """, aid=c["result_a_id"], bid=c["result_b_id"], cid=cid, rtype=c["result_type"])
            created.append(cid)

        # 跨构建体冲突
        for c in results.get("cross_construct_conflicts", []):
            existing = s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})-[r:CONTRADICTS]->(b:TechnicalResult {result_id: $bid})
                RETURN r.conflict_id AS cid LIMIT 1
            """, aid=c["result_a_id"], bid=c["result_b_id"]).single()
            if existing:
                continue
            cid = f"CONFLICT:{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (a:TechnicalResult {result_id: $aid})
                MATCH (b:TechnicalResult {result_id: $bid})
                CREATE (a)-[r:CONTRADICTS {
                    conflict_id: $cid, conflict_type: 'cross_construct_conflict',
                    strategy_id: $sid, result_type: $rtype, created_at: datetime()
                }]->(b)
            """, aid=c["result_a_id"], bid=c["result_b_id"],
                 cid=cid, sid=c["strategy_id"], rtype=c["result_type"])
            created.append(cid)

    if created:
        write_audit_event(
            driver, action_type="LINK_CREATE",
            object_type="TechnicalClaim",
            object_id=results.get("construct_id") or results.get("strategy_id") or "global",
            actor_id=actor_id, delta={"conflicts_created": len(created)},
            reason=f"技术冲突检测：{len(created)} 条 CONTRADICTS 关系",
        )
    return created


def list_conflicts_for_construct(driver, construct_id):
    """列出某构建体相关的所有 CONTRADICTS 关系。"""
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (a)-[r:CONTRADICTS]->(b)
            WHERE (a:TechnicalClaim OR a:TechnicalResult)
              AND (b:TechnicalClaim OR b:TechnicalResult)
              AND (r.conflict_type IN ['claim_status_conflict', 'result_direction_conflict'])
              AND EXISTS {
                  MATCH (a)-[]->(ec:EngineeredPhageConstruct {construct_id: $cid})
              }
            RETURN r.conflict_id AS conflict_id, r.conflict_type AS conflict_type,
                   labels(a)[0] AS a_label, a.claim_id AS a_claim_id, a.result_id AS a_result_id,
                   labels(b)[0] AS b_label, b.claim_id AS b_claim_id, b.result_id AS b_result_id
        """, cid=construct_id))
    return [dict(r) for r in rows]


# ==================================================================
# Part 3: IPMapping (原 ip_mapping_service.py)
# ==================================================================
import re

# 默认相似度阈值
DEFAULT_SIMILARITY_THRESHOLD = 0.30


def _token_set(s):
    """把字符串切成 token 集合（只保留长度 >=2 的字母数字/中文片段）。"""
    if not s:
        return set()
    return set(re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", s.lower()))


def _jaccard(a, b):
    """计算两个集合的 Jaccard 相似度；任一为空返回 0.0。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def map_patent_to_claims(driver, patent_family_id,
                         similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD,
                         top_k=5, actor_id="ip_mapping", persist=True):
    """
    把专利族映射到技术主张（基于文本相似度）。

    - 用 patent_family 的 claim_scope_summary + title 作为源文本
    - 与所有 TechnicalClaim 的 claim_text 做 Jaccard 相似度
    - 取 top_k 中相似度 >= 阈值的作为匹配
    - 可选持久化为 MAPS_TO 关系（幂等）

    Args:
        patent_family_id: 专利族 ID
        similarity_threshold: 相似度阈值
        top_k: 最多保留几个匹配
        actor_id: 操作者
        persist: 是否持久化

    Returns:
        Dict: {matches, created_relations, ...}
    """
    with driver.session() as s:
        pf = s.run("""
            MATCH (pf:PatentFamily {patent_family_id: $pfid})
            RETURN pf.patent_family_id AS pfid, pf.title AS title,
                   pf.claim_scope_summary AS summary
        """, pfid=patent_family_id).single()
        if not pf:
            raise ValueError(f"PatentFamily {patent_family_id} 不存在")
        claims = list(s.run("""
            MATCH (tc:TechnicalClaim)
            WHERE tc.claim_text IS NOT NULL AND tc.claim_text <> ''
            RETURN tc.claim_id AS cid, tc.claim_text AS text, tc.claim_type AS ctype
        """))

    # 计算相似度
    text = (pf["summary"] or "") + " " + (pf["title"] or "")
    pf_tokens = _token_set(text)
    if not pf_tokens:
        return {"patent_family_id": patent_family_id,
                "claim_scope_summary": pf["summary"], "matches": [],
                "created_relations": [],
                "note": "专利族没有 claim_scope_summary / title，无法匹配"}

    scored = []
    for c in claims:
        sim = _jaccard(pf_tokens, _token_set(c["text"]))
        if sim >= similarity_threshold:
            scored.append({"claim_id": c["cid"], "claim_text": c["text"][:120],
                           "claim_type": c["ctype"], "similarity": round(sim, 3)})
    scored.sort(key=lambda x: -x["similarity"])
    scored = scored[:top_k]

    # 可选：持久化
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
                        mapping_id: $mid, similarity: $sim,
                        threshold: $thr, created_at: datetime()
                    }]->(tc)
                """, pfid=patent_family_id, cid=m["claim_id"],
                     mid=mid, sim=m["similarity"], thr=similarity_threshold)
                m["already_mapped"] = False
                m["mapping_id"] = mid
                created.append({"mapping_id": mid, "claim_id": m["claim_id"],
                                "similarity": m["similarity"]})

        if created:
            write_audit_event(
                driver, action_type="LINK_CREATE",
                object_type="PatentFamily", object_id=patent_family_id,
                actor_id=actor_id, delta={"created_mappings": created},
                reason=f"专利-论文映射：{len(created)} 条",
            )

    return {"patent_family_id": patent_family_id,
            "claim_scope_summary": pf["summary"],
            "matches": scored, "created_relations": created}


def batch_map_all_patents(driver, similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD,
                          top_k=5, limit=100, actor_id="ip_mapping"):
    """
    批量把所有有 claim_scope_summary 的专利族做映射。
    """
    with driver.session() as s:
        pfids = [r["pfid"] for r in s.run("""
            MATCH (pf:PatentFamily)
            WHERE pf.claim_scope_summary IS NOT NULL AND pf.claim_scope_summary <> ''
            RETURN pf.patent_family_id AS pfid LIMIT $limit
        """, limit=limit)]

    total_created = 0
    details = []
    for pfid in pfids:
        try:
            r = map_patent_to_claims(driver, pfid,
                                     similarity_threshold=similarity_threshold,
                                     top_k=top_k, actor_id=actor_id, persist=True)
            total_created += len(r["created_relations"])
            details.append({"patent_family_id": pfid, "matches": len(r["matches"]),
                            "created": len(r["created_relations"])})
        except Exception as e:
            details.append({"patent_family_id": pfid, "error": str(e)})
    return {"total_patents_processed": len(pfids),
            "total_mappings_created": total_created, "details": details}


def list_mappings_for_patent(driver, patent_family_id):
    """列出某专利族的所有映射关系，按相似度倒序。"""
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (pf:PatentFamily {patent_family_id: $pfid})-[r:MAPS_TO]->(tc:TechnicalClaim)
            RETURN r.mapping_id AS mapping_id, r.similarity AS similarity,
                   tc.claim_id AS claim_id, tc.claim_type AS claim_type,
                   tc.claim_text AS claim_text
            ORDER BY r.similarity DESC
        """, pfid=patent_family_id))
    return [dict(r) for r in rows]