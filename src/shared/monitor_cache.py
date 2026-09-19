# src/shared/monitor_cache.py
"""
监控抓取缓存 —— 基于 Redis。

Key 设计: {prefix}:monitor:article:{md5(title|publish_time|creator)[:16]}

缓存内容（值）:
{
    "title": "...",
    "publish_time": "...",       # 发布时间 / 创建时间
    "creator": "...",            # 创建人 / 来源标签
    "source_url": "...",
    "parsed": {...},             # LLM 抽取的结构化结果
    "already_persisted": false,  # 是否已写入图数据库
    "cached_at": "...",
    "persisted_at": null,
}
"""
import hashlib
import json
from datetime import datetime
from typing import Optional

from config import get_redis_client, Config

# 缓存有效期：90 天（3 个月）
CACHE_TTL_SECONDS = 90 * 24 * 60 * 60


def _make_key(title: str, publish_time: str = "", creator: str = "") -> str:
    raw = "|".join([
        (title or "").strip(),
        (publish_time or "").strip(),
        (creator or "").strip(),
    ])
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return f"{Config.REDIS_KEY_PREFIX}:monitor:article:{h}"


def _decode(data):
    if data is None:
        return None
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except Exception:
            return None
    return data


def get_cached(title: str, publish_time: str = "", creator: str = "") -> Optional[dict]:
    """取缓存条目（未命中返回 None）。"""
    if not title:
        return None
    try:
        r = get_redis_client()
        raw = _decode(r.get(_make_key(title, publish_time, creator)))
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def set_cached(title: str, publish_time: str, parsed: dict,
               creator: str = "", source_url: str = "",
               already_persisted: bool = False) -> Optional[str]:
    """写入缓存条目，返回 key。"""
    if not title:
        return None
    try:
        r = get_redis_client()
        key = _make_key(title, publish_time, creator)
        payload = {
            "title": title,
            "publish_time": publish_time or "",
            "creator": creator or "",
            "source_url": source_url or "",
            "parsed": parsed,
            "already_persisted": already_persisted,
            "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "persisted_at": None,
        }
        r.set(key, json.dumps(payload, ensure_ascii=False), ex=CACHE_TTL_SECONDS)
        return key
    except Exception:
        return None


def mark_persisted(title: str, publish_time: str = "", creator: str = "") -> bool:
    """把某条缓存条目标记为「已入库」。"""
    if not title:
        return False
    try:
        r = get_redis_client()
        key = _make_key(title, publish_time, creator)
        raw = _decode(r.get(key))
        if not raw:
            return False
        payload = json.loads(raw)
        payload["already_persisted"] = True
        payload["persisted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        r.set(key, json.dumps(payload, ensure_ascii=False), ex=CACHE_TTL_SECONDS)
        return True
    except Exception:
        return False


def mark_persisted_by_url(url: str, title_hint: str = "") -> int:
    """
    按 source_url 模糊匹配所有缓存条目并标记为已入库。
    用于 `_apply_reviewed` 之后一次性同步。
    """
    if not url:
        return 0
    n = 0
    try:
        r = get_redis_client()
        pattern = f"{Config.REDIS_KEY_PREFIX}:monitor:article:*"
        for k in r.scan_iter(match=pattern, count=200):
            try:
                raw = _decode(r.get(k))
                if not raw:
                    continue
                payload = json.loads(raw)
                if payload.get("source_url") == url:
                    payload["already_persisted"] = True
                    payload["persisted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    r.set(k, json.dumps(payload, ensure_ascii=False), ex=CACHE_TTL_SECONDS)
                    n += 1
            except Exception:
                continue
    except Exception:
        pass
    return n


def cache_status(title: str, publish_time: str = "", creator: str = "") -> str:
    """返回一个人类可读的状态标签，用于展示。"""
    c = get_cached(title, publish_time, creator)
    if not c:
        return "🆕 未缓存"
    if c.get("already_persisted"):
        return "✅ 已入库"
    return "💾 已缓存（未入库）"