# src/ci/ci_monitor.py

import json
import uuid

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# =====================================================
# Models
# =====================================================

@dataclass
class MonitorSource:
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
    signal_id: str
    title: str
    organization: Optional[str]
    signal_type: str
    summary: str
    source_artifact_id: str
    confidence: float = 0.0
    review_status: str = "pending"   # pending / approved / rejected
    promoted_event_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


# =====================================================
# Utils
# =====================================================

def normalize_confidence(value):
    """0.9 / 90 / "0.9" → 0~1"""
    try:
        v = float(value)
        if v > 1:
            v = v / 100
        if v < 0:
            v = 0
        if v > 1:
            v = 1
        return v
    except Exception:
        return 0.0


# =====================================================
# Extractor
# =====================================================

class CISignalExtractor:
    def __init__(self, llm_client):
        self.llm = llm_client

    def extract(self, text: str):
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
            return {
                "title": "",
                "organization": None,
                "signal_type": "unknown",
                "summary": result,
                "confidence": 0.2,
            }


# =====================================================
# Signal Service
# =====================================================

class SignalService:
    def create_signal(self, extracted, source_artifact_id):
        return IntelligenceSignal(
            signal_id=str(uuid.uuid4()),
            title=extracted.get("title", ""),
            organization=extracted.get("organization"),
            signal_type=extracted.get("signal_type", "unknown"),
            summary=extracted.get("summary", ""),
            source_artifact_id=source_artifact_id,
            confidence=normalize_confidence(extracted.get("confidence", 0)),
        )


# =====================================================
# Neo4j Persistence —— Signal
# =====================================================

def save_signal(driver, signal: IntelligenceSignal):
    """写入 IntelligenceSignal 节点，并连到 SourceArtifact。"""
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
            signal_id=signal.signal_id,
            title=signal.title,
            organization=signal.organization,
            signal_type=signal.signal_type,
            summary=signal.summary,
            confidence=signal.confidence,
            review_status=signal.review_status,
            source_id=signal.source_artifact_id,
        )
    return signal.signal_id


# =====================================================
# Review —— 创建 / 审批
# =====================================================

def create_signal_review(driver, signal_id: str, reviewer_id: str = "pending"):
    """为 Signal 创建待审 Review 节点。"""
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
            signal_id=signal_id,
            review_id=review_id,
            reviewer_id=reviewer_id,
        )
    return review_id


def decide_signal_review(driver, signal_id: str, decision: str,
                         reviewer_id: str, comment: str = ""):
    """
    decision: 'approved' | 'rejected'
    同时更新 Review.decision 和 Signal.review_status。
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
            signal_id=signal_id,
            decision=decision,
            reviewer_id=reviewer_id,
            comment=comment,
        )
    return signal_id


# =====================================================
# Signal → IntelligenceEvent 晋升
# =====================================================

def promote_signal_to_event(
    driver,
    signal_id: str,
    *,
    event_type: str,
    title: str,
    factual_summary: str,
    organization_id: str,
    program_id: Optional[str] = None,
    event_date: Optional[str] = None,
    published_at: Optional[str] = None,
    actor_id: str = "signal_promoter",
):
    """
    已审核通过的 Signal → IntelligenceEvent。
    复用 capture_intelligence_event()，然后把 Signal 和 Event 关联起来。
    """
    from src.ci.event_service import capture_intelligence_event

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

    event_id = capture_intelligence_event(
        driver,
        event_type=event_type,
        title=title,
        factual_summary=factual_summary,
        organization_id=organization_id,
        program_id=program_id,
        event_date=event_date,
        published_at=published_at,
        source_ids=source_ids,
        actor_id=actor_id,
    )

    with driver.session() as session:
        session.run(
            """
            MATCH (s:IntelligenceSignal { signal_id: $sid })
            MATCH (e:IntelligenceEvent  { event_id:  $eid })
            MERGE (s)-[:PROMOTED_TO]->(e)
            SET s.promoted_event_id = $eid
            """,
            sid=signal_id,
            eid=event_id,
        )

    return event_id


# =====================================================
# Main Service —— 完整链路
# =====================================================

class CIMonitorService:
    """
    文章 → SourceArtifact → Signal → Review（待审）
    审批后 → IntelligenceEvent →（由 Competitor Brief 消费）
    """

    def __init__(self, llm_client, driver=None):
        self.extractor = CISignalExtractor(llm_client)
        self.signal_service = SignalService()
        self.driver = driver

    # ---------- 纯对象构建（不落库） ----------

    def process_article(self, text: str, source_artifact_id: str) -> IntelligenceSignal:
        extracted = self.extractor.extract(text)
        return self.signal_service.create_signal(extracted, source_artifact_id)

    # ---------- 落库：Article → Signal → Review(pending) ----------

    def ingest_article(
        self,
        text: str,
        source_artifact_id: str,
        *,
        reviewer_id: str = "pending",
    ) -> dict:
        if self.driver is None:
            raise RuntimeError("CIMonitorService.ingest_article 需要 driver")

        signal = self.process_article(text, source_artifact_id)
        save_signal(self.driver, signal)
        review_id = create_signal_review(self.driver, signal.signal_id, reviewer_id)
        return {"signal": signal, "review_id": review_id}

    # ---------- 审批 ----------

    def review_signal(
        self,
        signal_id: str,
        decision: str,
        *,
        reviewer_id: str,
        comment: str = "",
    ):
        if self.driver is None:
            raise RuntimeError("CIMonitorService.review_signal 需要 driver")
        return decide_signal_review(
            self.driver, signal_id, decision, reviewer_id, comment
        )

    # ---------- 通过后晋升为事件 ----------

    def promote(self, signal_id: str, **event_kwargs):
        if self.driver is None:
            raise RuntimeError("CIMonitorService.promote 需要 driver")
        return promote_signal_to_event(self.driver, signal_id, **event_kwargs)