# src/agents/core/intent_router.py
"""基于关键词的确定性意图识别。不调用 LLM。"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class IntentType(str, Enum):
    SCI_S1_BATCH_COMPLETENESS = "SCI_S1_BATCH_COMPLETENESS"
    SCI_S2_EVIDENCE_PACKAGE = "SCI_S2_EVIDENCE_PACKAGE"
    INT_I1_PERIODIC_BRIEF = "INT_I1_PERIODIC_BRIEF"
    UNKNOWN = "UNKNOWN"


@dataclass
class IntentResult:
    intent: IntentType
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    message: str = ""

    def to_dict(self) -> dict:
        return {"intent": self.intent.value, "params": self.params, "confidence": self.confidence, "message": self.message}


_SCI_S1_KEYWORDS = ["批次完整性", "实验批次", "批次检查", "数据完整性", "batch completeness", "batch check"]
_SCI_S2_KEYWORDS = ["证据包", "证据包草稿", "evidence package"]
_I1_KEYWORDS = ["情报简报", "周期简报", "竞争简报", "情报周报", "情报月报", "intelligence brief", "periodic brief"]

_BATCH_ID_PATTERNS = [re.compile(r"\bBATCH[-_][A-Za-z0-9_-]+\b"), re.compile(r"\bTEST[-_]BATCH[-_][A-Za-z0-9_-]+\b")]
_PATHOGEN_ID_PATTERNS = [re.compile(r"\bPATH-[A-Za-z0-9-]+\b"), re.compile(r"PATH[:\s]+([A-Za-z0-9-]+)")]

# ★ 优化：支持匹配 PKP005 这种纯大写字母+数字，也支持 PHAGE-PKP005
_PHAGE_ID_PATTERNS = [
    re.compile(r"\bPHAGE[-_][A-Za-z0-9-]+\b"), 
    re.compile(r"\bPHG-[A-Za-z0-9-]+\b"),
    re.compile(r"\b[A-Z]{2,}\d{3,}\b") 
]
# ★ 优化：支持匹配 HS-001 或纯数字/字母组合
_HOST_ID_PATTERNS = [
    re.compile(r"\bHS-[A-Za-z0-9-]+\b"), 
    re.compile(r"\bHOST[-_][A-Za-z0-9-]+\b")
]
_DATE_RANGE_PATTERNS = [re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:至|到|~|-)\s*(\d{4}-\d{2}-\d{2})"), re.compile(r"从\s*(\d{4}-\d{2}-\d{2})\s*到\s*(\d{4}-\d{2}-\d{2})")]


class IntentRouter:
    def route(self, query: str) -> IntentResult:
        if not query or not query.strip():
            return IntentResult(intent=IntentType.UNKNOWN, message="请输入任务描述")

        text = query.strip()
        lowered = text.lower()

        # 1. I1
        if any(kw in lowered for kw in _I1_KEYWORDS):
            pathogen_id = self._extract_pathogen_id(text)
            date_from, date_to = self._extract_date_range(text)
            return IntentResult(intent=IntentType.INT_I1_PERIODIC_BRIEF, params={"pathogen_id": pathogen_id, "date_from": date_from, "date_to": date_to}, message="识别为 INT-I1")

        # 2. S2 证据包
        if any(kw in lowered for kw in _SCI_S2_KEYWORDS):
            phage_id = self._extract_phage_id(text)
            host_id = self._extract_host_id(text)
            return IntentResult(intent=IntentType.SCI_S2_EVIDENCE_PACKAGE, params={"phage_id": phage_id, "host_strain_id": host_id}, message="识别为 SCI-S2 证据包")

        # 3. S1 批次完整性
        sci_hit = any(kw.lower() in lowered for kw in _SCI_S1_KEYWORDS)
        if sci_hit or ("批次" in text and ("完整性" in text or "检查" in text)):
            batch_id = self._extract_batch_id(text)
            return IntentResult(intent=IntentType.SCI_S1_BATCH_COMPLETENESS, params={"experiment_batch_id": batch_id}, message="识别为 SCI-S1")

        return IntentResult(intent=IntentType.UNKNOWN, message="当前仅支持 SCI-S1、SCI-S2 和 INT-I1 任务。")

    @staticmethod
    def _extract_batch_id(text: str) -> str:
        for p in _BATCH_ID_PATTERNS:
            m = p.search(text)
            if m: return m.group(0)
        return ""

    @staticmethod
    def _extract_pathogen_id(text: str) -> str:
        for p in _PATHOGEN_ID_PATTERNS:
            m = p.search(text)
            if m: return m.group(1) if m.lastindex else m.group(0)
        return ""

    @staticmethod
    def _extract_phage_id(text: str) -> str:
        for p in _PHAGE_ID_PATTERNS:
            m = p.search(text)
            if m: return m.group(0)
        return ""

    @staticmethod
    def _extract_host_id(text: str) -> str:
        for p in _HOST_ID_PATTERNS:
            m = p.search(text)
            if m: return m.group(0)
        return ""

    @staticmethod
    def _extract_date_range(text: str):
        for p in _DATE_RANGE_PATTERNS:
            m = p.search(text)
            if m: return m.group(1), m.group(2)
        return "", ""