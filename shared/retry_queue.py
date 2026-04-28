"""retry_queue — 失败任务延时重试队列。

设计：
- 失败的子任务（脚本）写入 data/retry_queue.json，带 `retry_after` 时间戳
- daily_sync / weekly_sync 在 Phase 0（主流水线开始前）扫一遍队列，跑所有
  retry_after <= now 的任务（即"到期"的）
- 单条记录尝试次数到上限就移除（永久失败），写 sync_state mark_failure
- 永久失败的 kind 集合：login_required（cookie 失效，重试也没用）

Schema (data/retry_queue.json):
{
  "version": 1,
  "items": [
    {
      "id": "<uuid>",
      "script": "comment_label",
      "queued_at": "ISO8601",
      "first_failure_at": "ISO8601",
      "retry_after": "ISO8601",
      "attempts": int,            # 已尝试次数（含原始那次）
      "max_attempts": 5,
      "last_error": str,
      "last_kind": str | None,
    }
  ]
}

退避策略（attempts → 下次重试间隔）：
  1 → 5min   2 → 30min   3 → 2h   4 → 6h   5 → 12h（封顶）
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = _PROJECT_ROOT / "data" / "retry_queue.json"

DEFAULT_MAX_ATTEMPTS = 5

# kind 在这个集合的失败认为不该自动重试（要人工修）
PERMANENT_FAILURE_KINDS = {"login_required"}

# 退避表（分钟）
_BACKOFF_MINUTES = [5, 30, 120, 360, 720]

_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _load() -> dict:
    if not QUEUE_PATH.exists():
        return {"version": 1, "items": []}
    try:
        d = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or "items" not in d:
            return {"version": 1, "items": []}
        return d
    except Exception:
        return {"version": 1, "items": []}


def _save(data: dict) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _mirror_to_redis(data)


# ---- Redis 镜像 ----------------------------------------------------------

REDIS_ZSET = "retry_queue"          # ZSET 存 item_id score=retry_after_ts
REDIS_HASH_PREFIX = "retry:"        # HASH 存 item 详情


def _redis():
    """延迟 import 避免循环依赖；Redis 不可用返回 None。"""
    try:
        from shared import db as _db
        return _db.redis_client()
    except Exception:
        return None


def _mirror_to_redis(data: dict) -> None:
    """把整个队列状态镜像到 Redis（覆盖式）。失败静默。"""
    rc = _redis()
    if rc is None:
        return
    try:
        # 清掉旧的
        old_ids = rc.zrange(REDIS_ZSET, 0, -1) or []
        if old_ids:
            for oid in old_ids:
                rc.delete(f"{REDIS_HASH_PREFIX}{oid}")
            rc.delete(REDIS_ZSET)
        # 写新的
        for it in data.get("items") or []:
            iid = it.get("id")
            if not iid:
                continue
            try:
                ts = datetime.fromisoformat(it["retry_after"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                score = ts.timestamp()
            except Exception:
                score = 0
            rc.zadd(REDIS_ZSET, {iid: score})
            clean = {k: ("" if v is None else str(v)) for k, v in it.items()}
            rc.hset(f"{REDIS_HASH_PREFIX}{iid}", mapping=clean)
    except Exception:
        pass


def _next_retry_at(attempts: int) -> str:
    """attempts 次后下次允许重试的时间戳。"""
    idx = min(max(attempts - 1, 0), len(_BACKOFF_MINUTES) - 1)
    delay = timedelta(minutes=_BACKOFF_MINUTES[idx])
    return (_now() + delay).isoformat(timespec="seconds")


def should_enqueue(error_kind: Optional[str]) -> bool:
    """判断这种失败该不该重试。"""
    return (error_kind or "") not in PERMANENT_FAILURE_KINDS


def enqueue(
    script: str,
    error: str,
    error_kind: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Optional[str]:
    """注册一次失败 → 下次主同步时重试。

    返回新增 / 更新的 item_id；如果 kind 在 PERMANENT_FAILURE_KINDS 则不入队，返回 None。
    同名 script 的旧记录会被合并（attempts += 1，retry_after 重排）。
    """
    if not should_enqueue(error_kind):
        return None
    with _lock:
        data = _load()
        # 合并：相同 script 的现存记录覆盖（保留 first_failure_at）
        existing = next((it for it in data["items"] if it.get("script") == script), None)
        if existing:
            existing["attempts"] = int(existing.get("attempts") or 1) + 1
            existing["last_error"] = (error or "")[:500]
            existing["last_kind"] = error_kind
            existing["retry_after"] = _next_retry_at(existing["attempts"])
            existing["queued_at"] = _now_iso()
            item_id = existing["id"]
            # 超过 max_attempts 就清掉
            if existing["attempts"] >= existing.get("max_attempts", max_attempts):
                data["items"].remove(existing)
                _save(data)
                return None
            _save(data)
            return item_id
        # 新增
        item = {
            "id": uuid.uuid4().hex[:12],
            "script": script,
            "queued_at": _now_iso(),
            "first_failure_at": _now_iso(),
            "retry_after": _next_retry_at(1),  # attempts=1 → 5min 后
            "attempts": 1,
            "max_attempts": max_attempts,
            "last_error": (error or "")[:500],
            "last_kind": error_kind,
        }
        data["items"].append(item)
        _save(data)
        return item["id"]


def due_items(now: Optional[datetime] = None) -> list[dict]:
    """返回 retry_after <= now 的所有项（按 retry_after 升序）。"""
    n = now or _now()
    with _lock:
        data = _load()
    out = []
    for it in data["items"]:
        try:
            ra = datetime.fromisoformat(it["retry_after"])
            if ra.tzinfo is None:
                ra = ra.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ra <= n:
            out.append(it)
    out.sort(key=lambda x: x.get("retry_after", ""))
    return out


def remove(item_id: str) -> bool:
    """重试成功后调，返回是否找到并删除。"""
    with _lock:
        data = _load()
        before = len(data["items"])
        data["items"] = [it for it in data["items"] if it.get("id") != item_id]
        if len(data["items"]) == before:
            return False
        _save(data)
        return True


def remove_by_script(script: str) -> bool:
    """按 script 名删（手动同步成功后调，因为可能不知道 item_id）。"""
    with _lock:
        data = _load()
        before = len(data["items"])
        data["items"] = [it for it in data["items"] if it.get("script") != script]
        if len(data["items"]) == before:
            return False
        _save(data)
        return True


def update_retry(item_id: str, error: str, error_kind: Optional[str] = None) -> Optional[dict]:
    """重试又失败了 → 增 attempts，重排 retry_after。返回更新后的 item，或 None 如果到达上限被清掉。"""
    with _lock:
        data = _load()
        it = next((x for x in data["items"] if x.get("id") == item_id), None)
        if not it:
            return None
        # 永久失败的 kind → 直接移除
        if not should_enqueue(error_kind):
            data["items"].remove(it)
            _save(data)
            return None
        it["attempts"] = int(it.get("attempts") or 1) + 1
        it["last_error"] = (error or "")[:500]
        it["last_kind"] = error_kind
        it["retry_after"] = _next_retry_at(it["attempts"])
        it["queued_at"] = _now_iso()
        if it["attempts"] >= it.get("max_attempts", DEFAULT_MAX_ATTEMPTS):
            data["items"].remove(it)
            _save(data)
            return None
        _save(data)
        return it


def snapshot() -> dict:
    """整队列拷贝（dashboard / 调试用）。"""
    with _lock:
        return _load()


def clear() -> None:
    """清空队列（手动 / 测试用）。"""
    with _lock:
        _save({"version": 1, "items": []})


if __name__ == "__main__":
    import sys
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
    sys.exit(0)
