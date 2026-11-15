# src/agents/core/timeline_service.py
"""Agent 任务时间线查询（只读）。

- get_task_timeline：任务相关全部 AuditEvent；
- get_relation_request_timeline：关系变更申请相关 AuditEvent（第 7 批使用）。
"""
import json
from typing import Optional

from neo4j import Driver


class AgentTimelineService:
    def __init__(
        self, driver: Driver, *, database: Optional[str] = None
    ) -> None:
        self.driver = driver
        self.database = database

    @staticmethod
    def _parse_delta(value):
        if not value:
            return None
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {"raw": str(value)}

    def get_task_timeline(
        self, task_id: str, *, limit: int = 500
    ) -> list:
        safe_limit = max(1, min(int(limit), 1000))
        with self.driver.session(database=self.database) as session:
            records = session.run(
                """
                MATCH (a:AuditEvent)
                WHERE a.task_id = $task_id OR a.object_id = $task_id
                RETURN a.audit_id AS event_id,
                       a.action_type AS event_type,
                       a.object_type AS object_type,
                       a.object_id AS object_id,
                       a.actor_id AS actor_id,
                       a.reason AS reason,
                       a.delta AS delta,
                       a.step_id AS step_id,
                       a.timestamp AS timestamp
                ORDER BY a.timestamp ASC
                LIMIT $limit
                """,
                task_id=task_id,
                limit=safe_limit,
            )
            events = []
            for r in records:
                e = dict(r)
                e["delta"] = self._parse_delta(e.get("delta"))
                events.append(e)
            return events

    def get_relation_request_timeline(
        self, request_id: str, *, limit: int = 200
    ) -> list:
        """关系变更申请相关事件（兼容查询，依赖 delta 包含 request_id）。"""
        safe_limit = max(1, min(int(limit), 500))
        with self.driver.session(database=self.database) as session:
            records = session.run(
                """
                MATCH (a:AuditEvent)
                WHERE a.object_id = $request_id
                   OR (a.action_type = 'RELATION_CREATE'
                       AND a.delta CONTAINS $request_id)
                RETURN a.audit_id AS event_id,
                       a.action_type AS event_type,
                       a.object_type AS object_type,
                       a.object_id AS object_id,
                       a.actor_id AS actor_id,
                       a.reason AS reason,
                       a.delta AS delta,
                       a.timestamp AS timestamp
                ORDER BY a.timestamp ASC
                LIMIT $limit
                """,
                request_id=request_id,
                limit=safe_limit,
            )
            events = []
            for r in records:
                e = dict(r)
                e["delta"] = self._parse_delta(e.get("delta"))
                events.append(e)
            return events