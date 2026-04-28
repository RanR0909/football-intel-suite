"""sync_state — 各抓取源的运行状态持久化（last_success / last_attempt / cookie_status）。

orchestrator 用它做 3 件事：
- 决定要不要跳过：is_fresh(source, max_age_hours)
- 记录成功/失败：mark_success(source) / mark_failure(source, kind, msg)
- 追踪 Playwright 登录态：mark_cookie_expired(source) / get_cookie_status(source)

dashboard 后续会读 data/sync_state.json 在顶部显示"上次更新"和 cookie 失效告警。

Schema:
{
  "version": 1,
  "sources": {
    "<source>": {
      "last_success": "ISO8601",
      "last_attempt": "ISO8601",
      "last_failure": "ISO8601" | null,
      "failure_kind": "timeout|login_required|api_error|..." | null,
      "failure_msg": str | null,
      "cookie_status": "ok|expired|unknown",   # 仅 Playwright 源
      "consecutive_failures": int
    }
  }
}
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = _PROJECT_ROOT / "data" / "sync_state.json"

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    if not STATE_PATH.exists():
        return {"version": 1, "sources": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "sources" not in data:
            return {"version": 1, "sources": {}}
        return data
    except Exception:
        return {"version": 1, "sources": {}}


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_source(state: dict, source: str) -> dict:
    sources = state.setdefault("sources", {})
    if source not in sources:
        sources[source] = {
            "last_success": None,
            "last_attempt": None,
            "last_failure": None,
            "failure_kind": None,
            "failure_msg": None,
            "cookie_status": "unknown",
            "consecutive_failures": 0,
        }
    return sources[source]


# ---- 公开 API ------------------------------------------------------------

def is_fresh(source: str, max_age_hours: float) -> bool:
    """上次成功 < max_age_hours 之前返回 True（orchestrator 用来跳过）。"""
    with _lock:
        state = _load()
    s = state.get("sources", {}).get(source)
    if not s or not s.get("last_success"):
        return False
    try:
        last = datetime.fromisoformat(s["last_success"])
    except Exception:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last < timedelta(hours=max_age_hours)


def get_last_success(source: str) -> Optional[str]:
    with _lock:
        state = _load()
    s = state.get("sources", {}).get(source) or {}
    return s.get("last_success")


def mark_attempt(source: str) -> None:
    """跑之前记录一次（失败时用得上）。"""
    with _lock:
        state = _load()
        s = _get_source(state, source)
        s["last_attempt"] = _now()
        _save(state)


def mark_success(source: str) -> None:
    with _lock:
        state = _load()
        s = _get_source(state, source)
        s["last_success"] = _now()
        s["last_attempt"] = s["last_attempt"] or s["last_success"]
        s["last_failure"] = None
        s["failure_kind"] = None
        s["failure_msg"] = None
        s["consecutive_failures"] = 0
        # 成功默认认为 cookie 健康；调用方覆盖更精准
        if s.get("cookie_status") in (None, "expired", "unknown"):
            # 只有 Playwright 源会显式 mark cookie；HTTP 源的 cookie_status 留 unknown
            pass
        _save(state)


def mark_failure(source: str, kind: str, msg: str = "") -> None:
    with _lock:
        state = _load()
        s = _get_source(state, source)
        s["last_attempt"] = _now()
        s["last_failure"] = s["last_attempt"]
        s["failure_kind"] = kind
        s["failure_msg"] = (msg or "")[:500]
        s["consecutive_failures"] = int(s.get("consecutive_failures") or 0) + 1
        _save(state)


def mark_cookie_ok(source: str) -> None:
    with _lock:
        state = _load()
        s = _get_source(state, source)
        s["cookie_status"] = "ok"
        _save(state)


def mark_cookie_expired(source: str) -> None:
    """Playwright 源检测到 LoginRequired 时调；orchestrator 据此发通知。"""
    with _lock:
        state = _load()
        s = _get_source(state, source)
        s["cookie_status"] = "expired"
        _save(state)


def get_cookie_status(source: str) -> str:
    with _lock:
        state = _load()
    s = state.get("sources", {}).get(source) or {}
    return s.get("cookie_status") or "unknown"


def snapshot() -> dict:
    """整份 state 拷贝（dashboard / 调试用）。"""
    with _lock:
        return _load()


if __name__ == "__main__":
    # CLI debug：python3 -m shared.sync_state
    import sys
    state = snapshot()
    print(json.dumps(state, ensure_ascii=False, indent=2))
    sys.exit(0)
