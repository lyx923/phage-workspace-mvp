# src/ci/event_service.py
"""
IntelligenceEvent / CI Monitor / IntelligenceUseEvent / Source Scoring
合并服务（PRD 12.2 / 16.2 / MCI-14）

包含四个部分：
    Part 1: IntelligenceEvent       —— 情报事件捕获与多来源合并
    Part 2: CI Monitor              —— 信号抽取、审核、晋升为事件
    Part 3: IntelligenceUseEvent    —— 情报产品使用记录
    Part 4: Source Scoring          —— 来源可信度评分
"""

# ==================================================================
# Part 1: IntelligenceEvent (原 event_service.py)
# ==================================================================
import uuid
import hashlib
from typing import Optional, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_event_id() -> str:
    """生成情报事件 ID（格式：CI:EVT:XXXXXXXX）。"""
    return f"CI:EVT:{uuid.uuid4().hex[:8].upper()}"


def _generate_dedup_key(event_type, organization_id, title, event_date):
    """
    生成去重 key（sha256 前 16 位 hex），
    由 event_type | organization_id | title | event_date 唯一确定。
    """
    raw = f"{event_type}|{organization_id}|{title}|{event_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def capture_intelligence_event(
    driver: Driver, event_type: str, title: str, factual_summary: str,
    organization_id: str, program_id: Optional[str] = None,
    event_date: Optional[str] = None, published_at: Optional[str] = None,
    source_ids: Optional[List[str]] = None, actor_id: str = "system",
    merge_on_duplicate: bool = True,
) -> str:
    """
    捕获情报事件（带去重合并）。

    流程：
        1. 计算 dedup_key，若已存在：
           - merge_on_duplicate=False → 抛异常
           - merge_on_duplicate=True  → 合并新来源到已有事件
        2. 不存在则创建新事件，建立 INVOLVES / AFFECTS / HAS_SOURCE 关系

    Args:
        event_type: 事件类型
        title: 标题
        factual_summary: 事实摘要
        organization_id: 涉及组织
        program_id: 影响项目（可选）
        event_date: 事件日期
        published_at: 发布时间
        source_ids: 来源 ID 列表
        actor_id: 操作者
        merge_on_duplicate: 是否合并到已有事件

    Returns:
        str: event_id
    """
    source_ids = source_ids or []
    dedup_key = _generate_dedup_key(event_type, organization_id, title, event_date or "")

    with driver.session() as session:
        # 检查是否已存在
        existing = session.run(
            "MATCH (e:IntelligenceEvent {deduplication_key: $key}) RETURN e.event_id AS id LIMIT 1",
            key=dedup_key,
        ).single()

        if existing:
            event_id = existing["id"]
            if not merge_on_duplicate:
                raise ValueError(f"重复事件已存在，ID: {event_id}")

            # --- 合并分支 ---
            merged_source_ids = []
            linked_org = False
            linked_program = False

            # 补齐 organization_id 属性
            session.run(
                "MATCH (e:IntelligenceEvent {event_id: $eid}) "
                "SET e.organization_id = COALESCE(e.organization_id, $oid)",
                eid=event_id, oid=organization_id,
            )

            # 合并来源
            for src_id in source_ids:
                chk = session.run(
                    "MATCH (s:SourceArtifact {source_id: $sid}) RETURN s LIMIT 1",
                    sid=src_id,
                ).single()
                if not chk:
                    raise ValueError(
                        f"SourceArtifact {src_id} 不存在，无法关联事件。"
                        f"请先调用 create_source_artifact() 创建。"
                    )
                already = session.run(
                    "MATCH (e:IntelligenceEvent {event_id: $eid})-[:HAS_SOURCE]->"
                    "(s:SourceArtifact {source_id: $sid}) RETURN 1 AS x LIMIT 1",
                    eid=event_id, sid=src_id,
                ).single()
                if already:
                    continue
                session.run(
                    "MATCH (e:IntelligenceEvent {event_id: $eid}) "
                    "MATCH (s:SourceArtifact {source_id: $sid}) "
                    "CREATE (e)-[:HAS_SOURCE]->(s)",
                    eid=event_id, sid=src_id,
                )
                merged_source_ids.append(src_id)

            # 合并组织
            org_chk = session.run(
                "MATCH (o:Organization {organization_id: $oid}) RETURN o LIMIT 1",
                oid=organization_id,
            ).single()
            if org_chk:
                already = session.run(
                    "MATCH (e:IntelligenceEvent {event_id: $eid})-[:INVOLVES]->"
                    "(o:Organization {organization_id: $oid}) RETURN 1 AS x LIMIT 1",
                    eid=event_id, oid=organization_id,
                ).single()
                if not already:
                    session.run(
                        "MATCH (e:IntelligenceEvent {event_id: $eid}) "
                        "MATCH (o:Organization {organization_id: $oid}) "
                        "CREATE (e)-[:INVOLVES]->(o)",
                        eid=event_id, oid=organization_id,
                    )
                    linked_org = True

            # 合并项目
            if program_id:
                prog_chk = session.run(
                    "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d LIMIT 1",
                    pid=program_id,
                ).single()
                if prog_chk:
                    already = session.run(
                        "MATCH (e:IntelligenceEvent {event_id: $eid})-[:AFFECTS]->"
                        "(d:DevelopmentProgram {program_id: $pid}) RETURN 1 AS x LIMIT 1",
                        eid=event_id, pid=program_id,
                    ).single()
                    if not already:
                        session.run(
                            "MATCH (e:IntelligenceEvent {event_id: $eid}) "
                            "MATCH (d:DevelopmentProgram {program_id: $pid}) "
                            "CREATE (e)-[:AFFECTS]->(d)",
                            eid=event_id, pid=program_id,
                        )
                        linked_program = True

            write_audit_event(
                driver, action_type="LINK_CREATE",
                object_type="IntelligenceEvent", object_id=event_id,
                actor_id=actor_id,
                delta={"merge": True, "merged_source_ids": merged_source_ids,
                       "linked_organization": linked_org, "linked_program": linked_program},
                reason=f"合并多来源到已有事件: {title}（新增 {len(merged_source_ids)} 个 SourceArtifact）",
            )
            return event_id

        # --- 新建分支 ---
        event_id = generate_event_id()
        session.run(
            """
            CREATE (e:IntelligenceEvent {
                event_id: $eid, event_type: $etype, title: $title,
                factual_summary: $summary,
                event_date: $evt_date, published_at: $pub_at,
                discovered_at: datetime(), created_at: datetime(),
                confidence: 'medium', materiality: 'medium',
                review_status: 'pending',
                deduplication_key: $dedup_key, organization_id: $oid
            })
            """,
            eid=event_id, etype=event_type, title=title, summary=factual_summary,
            evt_date=event_date, pub_at=published_at, dedup_key=dedup_key,
            oid=organization_id,
        )
        # INVOLVES 组织
        session.run(
            "MATCH (e:IntelligenceEvent {event_id: $eid}) "
            "MATCH (o:Organization {organization_id: $oid}) "
            "CREATE (e)-[:INVOLVES]->(o)",
            eid=event_id, oid=organization_id,
        )
        # AFFECTS 项目
        if program_id:
            session.run(
                "MATCH (e:IntelligenceEvent {event_id: $eid}) "
                "MATCH (d:DevelopmentProgram {program_id: $pid}) "
                "CREATE (e)-[:AFFECTS]->(d)",
                eid=event_id, pid=program_id,
            )
        # HAS_SOURCE 来源
        for src_id in source_ids:
            chk = session.run(
                "MATCH (s:SourceArtifact {source_id: $sid}) RETURN s LIMIT 1",
                sid=src_id,
            ).single()
            if not chk:
                raise ValueError(
                    f"SourceArtifact {src_id} 不存在，无法关联事件。"
                    f"请先调用 create_source_artifact() 创建。"
                )
            session.run(
                "MATCH (e:IntelligenceEvent {event_id: $eid}) "
                "MATCH (s:SourceArtifact {source_id: $sid}) "
                "CREATE (e)-[:HAS_SOURCE]->(s)",
                eid=event_id, sid=src_id,
            )

        write_audit_event(
            driver, action_type="CREATE",
            object_type="IntelligenceEvent", object_id=event_id,
            actor_id=actor_id,
            delta={"event_type": event_type, "title": title,
                   "organization_id": organization_id, "source_ids": source_ids},
            reason=f"捕获情报事件: {title}",
        )
        return event_id


# ==================================================================
# Part 2: CI Monitor (原 ci_monitor.py)
# ==================================================================
import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MonitorSource:
    """监控来源数据类。"""
    source_id: str
    name: str
    source_type: str
    url: Optional[str] = None
    priority: str = "medium"
    keywords: List[str] = field(default_factory=list)
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IntelligenceSignal:
    """情报信号数据类（信号在审核前只是候选事实）。"""
    signal_id: str
    title: str
    organization: Optional[str]
    signal_type: str
    summary: str
    source_artifact_id: str
    confidence: float = 0.0
    review_status: str = "pending"
    promoted_event_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


def normalize_confidence(value):
    """把置信度归一化到 [0, 1]；>1 时按百分数处理；非法值返回 0.0。"""
    try:
        v = float(value)
        if v > 1:
            v = v / 100
        v = max(0.0, min(v, 1.0))
        return v
    except Exception:
        return 0.0


class CISignalExtractor:
    """基于 LLM 的信号抽取器（只抽取文本明确出现的信息）。"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def extract(self, text: str):
        """从文本抽取信号；解析失败时返回降级结果。"""
        prompt = f"""
你是竞争情报事实抽取助手。

要求：
1. 只能抽取文本明确出现的信息。
2. 禁止推测。
3. 禁止补充背景知识。
4. 不确定字段返回空。

输出JSON:

{{
"title":"",
"organization":"",
"signal_type":"",
"summary":"",
"confidence":0
}}

文本:

{text}
"""
        result = self.llm.chat(prompt)
        try:
            return json.loads(result)
        except Exception:
            return {"title": "", "organization": None, "signal_type": "unknown",
                    "summary": result, "confidence": 0.2}


class SignalService:
    """信号服务：把抽取结果包装成 IntelligenceSignal 对象。"""

    def create_signal(self, extracted, source_artifact_id):
        """根据抽取结果创建信号对象。"""
        return IntelligenceSignal(
            signal_id=str(uuid.uuid4()),
            title=extracted.get("title", ""),
            organization=extracted.get("organization"),
            signal_type=extracted.get("signal_type", "unknown"),
            summary=extracted.get("summary", ""),
            source_artifact_id=source_artifact_id,
            confidence=normalize_confidence(extracted.get("confidence", 0)),
        )


def save_signal(driver, signal: IntelligenceSignal):
    """
    保存信号到 Neo4j，并建立 (SourceArtifact)-[:GENERATED_SIGNAL]->(信号) 关系。
    """
    with driver.session() as session:
        session.run(
            """
            MERGE (s:IntelligenceSignal { signal_id: $signal_id })
            SET s.title            = $title,
                s.organization     = $organization,
                s.signal_type      = $signal_type,
                s.summary          = $summary,
                s.confidence       = $confidence,
                s.review_status    = $review_status,
                s.created_at       = COALESCE(s.created_at, datetime())
            WITH s
            MATCH (src:SourceArtifact { source_id: $source_id })
            MERGE (src)-[:GENERATED_SIGNAL]->(s)
            """,
            signal_id=signal.signal_id, title=signal.title,
            organization=signal.organization, signal_type=signal.signal_type,
            summary=signal.summary, confidence=signal.confidence,
            review_status=signal.review_status,
            source_id=signal.source_artifact_id,
        )
    return signal.signal_id


def create_signal_review(driver, signal_id, reviewer_id="pending"):
    """为信号创建审核记录（ci_fact_review 类型）。"""
    review_id = str(uuid.uuid4())
    with driver.session() as session:
        session.run(
            """
            MATCH (s:IntelligenceSignal { signal_id: $signal_id })
            MERGE (r:Review { review_id: $review_id })
            SET r.review_type         = 'ci_fact_review',
                r.target_object_type  = 'IntelligenceSignal',
                r.target_object_id    = $signal_id,
                r.reviewer_id         = $reviewer_id,
                r.decision            = 'pending',
                r.comment             = '',
                r.created_at          = datetime()
            MERGE (r)-[:REVIEWS]->(s)
            """,
            signal_id=signal_id, review_id=review_id, reviewer_id=reviewer_id,
        )
    return review_id


def decide_signal_review(driver, signal_id, decision, reviewer_id, comment=""):
    """
    对信号审核做出决策（approved / rejected），并同步更新信号状态。
    """
    if decision not in ("approved", "rejected"):
        raise ValueError(f"非法审核决策: {decision}")
    with driver.session() as session:
        session.run(
            """
            MATCH (r:Review)-[:REVIEWS]->(s:IntelligenceSignal { signal_id: $signal_id })
            SET r.decision    = $decision,
                r.reviewer_id = $reviewer_id,
                r.comment     = $comment,
                r.decided_at  = datetime()
            SET s.review_status = $decision
            """,
            signal_id=signal_id, decision=decision,
            reviewer_id=reviewer_id, comment=comment,
        )
    return signal_id


def promote_signal_to_event(
    driver, signal_id, *, event_type, title, factual_summary,
    organization_id, program_id=None, event_date=None, published_at=None,
    actor_id="signal_promoter",
):
    """
    把已审核通过的信号晋升为情报事件。

    前置条件：
        - 信号 review_status = 'approved'
        - 信号有 GENERATED_SIGNAL 来源
    """
    with driver.session() as session:
        row = session.run(
            """
            MATCH (s:IntelligenceSignal { signal_id: $sid })
            WHERE s.review_status = 'approved'
            MATCH (src:SourceArtifact)-[:GENERATED_SIGNAL]->(s)
            RETURN src.source_id AS src_id
            """,
            sid=signal_id,
        ).single()
    if not row:
        raise ValueError(
            f"Signal {signal_id} 未通过审核或缺少 SourceArtifact，无法晋升为事件。"
        )
    source_ids = [row["src_id"]]

    # 晋升为事件
    event_id = capture_intelligence_event(
        driver, event_type=event_type, title=title, factual_summary=factual_summary,
        organization_id=organization_id, program_id=program_id,
        event_date=event_date, published_at=published_at,
        source_ids=source_ids, actor_id=actor_id,
    )
    # 建立 PROMOTED_TO 关系
    with driver.session() as session:
        session.run(
            """
            MATCH (s:IntelligenceSignal { signal_id: $sid })
            MATCH (e:IntelligenceEvent  { event_id:  $eid })
            MERGE (s)-[:PROMOTED_TO]->(e)
            SET s.promoted_event_id = $eid
            """,
            sid=signal_id, eid=event_id,
        )
    return event_id


class CIMonitorService:
    """CI Monitor 服务封装：抽取 → 保存 → 审核 → 晋升。"""

    def __init__(self, llm_client, driver=None):
        self.extractor = CISignalExtractor(llm_client)
        self.signal_service = SignalService()
        self.driver = driver

    def process_article(self, text, source_artifact_id):
        """仅抽取（不落库）。"""
        extracted = self.extractor.extract(text)
        return self.signal_service.create_signal(extracted, source_artifact_id)

    def ingest_article(self, text, source_artifact_id, *, reviewer_id="pending"):
        """抽取 → 落库 → 创建审核记录。"""
        if self.driver is None:
            raise RuntimeError("CIMonitorService.ingest_article 需要 driver")
        signal = self.process_article(text, source_artifact_id)
        save_signal(self.driver, signal)
        review_id = create_signal_review(self.driver, signal.signal_id, reviewer_id)
        return {"signal": signal, "review_id": review_id}

    def review_signal(self, signal_id, decision, *, reviewer_id, comment=""):
        """审核信号。"""
        if self.driver is None:
            raise RuntimeError("CIMonitorService.review_signal 需要 driver")
        return decide_signal_review(self.driver, signal_id, decision, reviewer_id, comment)

    def promote(self, signal_id, **event_kwargs):
        """把信号晋升为事件。"""
        if self.driver is None:
            raise RuntimeError("CIMonitorService.promote 需要 driver")
        return promote_signal_to_event(self.driver, signal_id, **event_kwargs)


# ==================================================================
# Part 3: IntelligenceUseEvent
# ==================================================================

def generate_use_event_id() -> str:
    """生成情报使用事件 ID（格式：CI:USE:XXXXXXXX）。"""
    return f"CI:USE:{uuid.uuid4().hex[:8].upper()}"


def record_intelligence_use(
    driver: Driver, product_id: str, consumer_type: str,
    consumer_id: str, use_purpose: str, context_note: Optional[str] = None,
    referenced_decision_id: Optional[str] = None, actor_id: str = "system",
) -> str:
    """
    记录一次情报产品使用事件。

    - 支持 DecisionBrief 和 IntelligenceProduct 两种产品
    - 建立 CONSUMES 关系
    - 如提供 referenced_decision_id，额外建立 TRIGGERS 关系
    """
    use_event_id = generate_use_event_id()
    with driver.session() as session:
        # 校验产品存在
        product = session.run(
            """
            MATCH (b)
            WHERE (b:DecisionBrief AND b.brief_id = $pid)
               OR (b:IntelligenceProduct AND b.brief_id = $pid)
            RETURN b LIMIT 1
            """,
            pid=product_id,
        ).single()
        if not product:
            raise ValueError(
                f"情报产品 {product_id} 不存在（既不是 DecisionBrief 也不是 IntelligenceProduct），"
                f"无法记录使用事件。"
            )
        # 创建使用事件
        session.run(
            """
            CREATE (u:IntelligenceUseEvent {
                use_event_id: $use_event_id, product_id: $product_id,
                consumer_type: $consumer_type, consumer_id: $consumer_id,
                use_purpose: $use_purpose, context_note: $context_note,
                actor_id: $actor_id, used_at: datetime()
            })
            """,
            use_event_id=use_event_id, product_id=product_id,
            consumer_type=consumer_type, consumer_id=consumer_id,
            use_purpose=use_purpose, context_note=context_note, actor_id=actor_id,
        )
        # CONSUMES 关系
        session.run(
            """
            MATCH (u:IntelligenceUseEvent {use_event_id: $uid})
            MATCH (b)
            WHERE (b:DecisionBrief AND b.brief_id = $pid)
               OR (b:IntelligenceProduct AND b.brief_id = $pid)
            CREATE (u)-[:CONSUMES]->(b)
            """,
            uid=use_event_id, pid=product_id,
        )
        # 可选：TRIGGERS 决策
        if referenced_decision_id:
            decision = session.run(
                "MATCH (d:DecisionRecord {decision_id: $did}) RETURN d",
                did=referenced_decision_id,
            ).single()
            if decision:
                session.run(
                    "MATCH (u:IntelligenceUseEvent {use_event_id: $uid}) "
                    "MATCH (d:DecisionRecord {decision_id: $did}) "
                    "CREATE (u)-[:TRIGGERS]->(d)",
                    uid=use_event_id, did=referenced_decision_id,
                )
        write_audit_event(
            driver, action_type="CREATE",
            object_type="IntelligenceUseEvent", object_id=use_event_id,
            actor_id=actor_id,
            delta={"product_id": product_id, "consumer_type": consumer_type,
                   "consumer_id": consumer_id, "use_purpose": use_purpose},
            reason=f"{consumer_type} 团队消费情报产品 {product_id}",
        )
        return use_event_id


# ==================================================================
# Part 4: Source Scoring (原 source_scoring.py)
# ==================================================================
from datetime import datetime as _dt

# 基础分（按 credibility_tier）
BASE_TIER_SCORE = {"primary": 80, "secondary": 55, "tertiary": 35, "unknown": 20}
# 类型加分（按 source_type）
SOURCE_TYPE_BONUS = {
    "regulatory_filing": 10, "clinical_trial_registry": 8,
    "peer_reviewed_paper": 10, "literature": 8, "patent": 6,
    "press_release": 2, "url_scrape": 0, "news": 0,
    "user_input": -5, "monitor_auto": -3,
}


def _score_one(sa):
    """
    内部函数：对单个 SourceArtifact 计算可信度得分。

    规则：
        base = BASE_TIER_SCORE[tier]
        + SOURCE_TYPE_BONUS[source_type]
        + 5（有 url）
        + 5（有 published_date）
        + 5（review_status = approved）
        - 10（review_status = disputed）
    最终裁剪到 [0, 100]。
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
    rs = (sa.get("review_status") or "").lower()
    if rs == "approved":
        score += 5
        reasons.append("review_status=approved +5")
    elif rs == "disputed":
        score -= 10
        reasons.append("review_status=disputed -10")
    score = max(0, min(100, score))
    return {"score": score, "tier": tier, "source_type": stype, "reasons": reasons}


def score_source_artifact(driver, source_id, actor_id="source_scoring"):
    """
    对单个来源评分并写回 Neo4j。
    """
    with driver.session() as s:
        row = s.run("""
            MATCH (sa:SourceArtifact {source_id: $sid})
            RETURN sa.source_id AS source_id, sa.source_type AS source_type,
                   sa.credibility_tier AS credibility_tier, sa.url AS url,
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
        driver, action_type="UPDATE",
        object_type="SourceArtifact", object_id=source_id,
        actor_id=actor_id, delta={"credibility_score": result["score"]},
        reason=f"来源可信度评分: {result['score']}（{'; '.join(result['reasons'][:3])}）",
    )
    result["source_id"] = source_id
    return result


def batch_score_sources(driver, limit=500, actor_id="source_scoring"):
    """
    批量对未评分的 SourceArtifact 评分。
    """
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (sa:SourceArtifact)
            WHERE sa.credibility_score IS NULL
            RETURN sa.source_id AS sid LIMIT $limit
        """, limit=limit))
    scored = 0
    errors = []
    for r in rows:
        try:
            score_source_artifact(driver, r["sid"], actor_id=actor_id)
            scored += 1
        except Exception as e:
            errors.append(f"{r['sid']}: {e}")
    return {"total_candidates": len(rows), "scored": scored, "errors": errors[:10]}


def get_source_score(driver, source_id):
    """查询单个来源的评分信息。"""
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