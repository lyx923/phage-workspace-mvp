# src/agents/core/retry_policy.py
"""Agent 步骤重试策略。"""
from dataclasses import dataclass
from typing import FrozenSet

from .errors import AgentErrorCode


DEFAULT_RETRYABLE_CODES: FrozenSet[str] = frozenset(
    {
        AgentErrorCode.TOOL_TIMEOUT.value,
        "AGENT_TOOL_EXECUTION_FAILED",
        "AGENT_TRANSIENT_DATABASE_ERROR",
        "AGENT_TRANSIENT_NETWORK_ERROR",
    }
)


DEFAULT_NON_RETRYABLE_CODES: FrozenSet[str] = frozenset(
    {
        AgentErrorCode.PERMISSION_DENIED.value,
        AgentErrorCode.APPROVAL_REQUIRED.value,
        AgentErrorCode.TOOL_INPUT_INVALID.value,
        AgentErrorCode.TOOL_NOT_REGISTERED.value,
        AgentErrorCode.TOOL_DISABLED.value,
        AgentErrorCode.TOOL_DOMAIN_MISMATCH.value,
        AgentErrorCode.CONTEXT_INVALID.value,
        AgentErrorCode.CONTEXT_EXPIRED.value,
        AgentErrorCode.CONTEXT_HASH_MISMATCH.value,
        AgentErrorCode.PLAN_VERSION_MISMATCH.value,
        AgentErrorCode.MODEL_INELIGIBLE.value,
        AgentErrorCode.VALIDATION_BLOCKED.value,
    }
)


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    reason: str
    next_retry_count: int


class RetryPolicy:
    def __init__(
        self,
        *,
        max_retries: int,
        retryable_codes: FrozenSet[str] = DEFAULT_RETRYABLE_CODES,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0")
        self.max_retries = max_retries
        self.retryable_codes = retryable_codes

    def evaluate(
        self,
        *,
        error_code: str | None,
        retry_count: int,
        can_retry: bool,
    ) -> RetryDecision:
        if not can_retry:
            return RetryDecision(
                allowed=False,
                reason="步骤定义不允许重试",
                next_retry_count=retry_count,
            )
        if not error_code:
            return RetryDecision(
                allowed=False,
                reason="步骤没有可识别的错误代码",
                next_retry_count=retry_count,
            )
        if error_code in DEFAULT_NON_RETRYABLE_CODES:
            return RetryDecision(
                allowed=False,
                reason="该错误属于不可重试类型",
                next_retry_count=retry_count,
            )
        if error_code not in self.retryable_codes:
            return RetryDecision(
                allowed=False,
                reason="错误未列入可重试清单",
                next_retry_count=retry_count,
            )
        if retry_count >= self.max_retries:
            return RetryDecision(
                allowed=False,
                reason="已达到最大重试次数",
                next_retry_count=retry_count,
            )
        return RetryDecision(
            allowed=True,
            reason="允许受控重试",
            next_retry_count=retry_count + 1,
        )