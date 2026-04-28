"""shared/db — MySQL (SQLAlchemy) + Redis 客户端 + 健康检查。

设计：
- 配置走 env：MYSQL_DSN / REDIS_URL；任一未配置 → 该客户端 None（dao 层降级 JSON-only）
- 连接懒初始化，进程级单例（线程安全）
- 健康检查供 dashboard /api/db/status 用

env 例（.env.local 或 ~/.intelops-secrets）：
  MYSQL_DSN=mysql+pymysql://intelops:dev@localhost:3306/football_intel?charset=utf8mb4
  REDIS_URL=redis://localhost:6379/0
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

log = logging.getLogger("shared.db")

# ---- SQLAlchemy 引擎 ------------------------------------------------------

_engine_lock = threading.Lock()
_engine = None  # type: ignore
_session_factory = None  # type: ignore


def _build_engine():
    """懒初始化 SQLAlchemy engine + sessionmaker。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    dsn = (os.environ.get("MYSQL_DSN") or "").strip()
    if not dsn:
        return None, None
    # SQLite（测试用）不接受 pool_size / max_overflow；只对 MySQL 生效
    kwargs = dict(pool_pre_ping=True, future=True)
    if not dsn.startswith("sqlite"):
        kwargs.update(pool_recycle=3600, pool_size=5, max_overflow=10)
    eng = create_engine(dsn, **kwargs)
    factory = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    return eng, factory


def engine():
    """返回 SQLAlchemy Engine（首次调用时懒初始化）；MYSQL_DSN 未配置返回 None。"""
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            _engine, _session_factory = _build_engine()
    return _engine


def session_factory():
    """返回 sessionmaker；MYSQL_DSN 未配置返回 None。"""
    if _session_factory is None:
        engine()
    return _session_factory


def session():
    """便捷上下文：with db.session() as s: s.add(...) — 自动 commit / rollback。"""
    factory = session_factory()
    if factory is None:
        return _NullSessionContext()
    return _SessionCtx(factory())


class _SessionCtx:
    def __init__(self, sess):
        self.sess = sess

    def __enter__(self):
        return self.sess

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.sess.commit()
            else:
                self.sess.rollback()
        finally:
            self.sess.close()


class _NullSessionContext:
    """MySQL 未配置时返回的"假" context — 进入直接报 not configured。"""

    def __enter__(self):
        raise RuntimeError("MYSQL_DSN 未配置；db.session() 不可用")

    def __exit__(self, *a):
        return False


def is_mysql_enabled() -> bool:
    return engine() is not None


# ---- Redis 客户端 --------------------------------------------------------

_redis_lock = threading.Lock()
_redis = None  # type: ignore


def _build_redis():
    import redis as _r
    url = (os.environ.get("REDIS_URL") or "").strip()
    if not url:
        return None
    return _r.Redis.from_url(url, decode_responses=True, socket_timeout=5)


def redis_client():
    """返回 redis.Redis 客户端（懒初始化）；REDIS_URL 未配置返回 None。"""
    global _redis
    if _redis is not None:
        return _redis
    with _redis_lock:
        if _redis is None:
            _redis = _build_redis()
    return _redis


def is_redis_enabled() -> bool:
    return redis_client() is not None


# ---- 健康检查 ------------------------------------------------------------

def health() -> dict:
    """返回 MySQL / Redis 状态汇总。供 /api/db/status 用。"""
    out = {
        "mysql": {"enabled": False, "ok": False, "error": None, "tables": {}},
        "redis": {"enabled": False, "ok": False, "error": None, "memory_human": None,
                  "keys_sample": []},
    }

    # MySQL
    eng = engine()
    if eng is not None:
        out["mysql"]["enabled"] = True
        try:
            from sqlalchemy import text
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            # 各表行数
            try:
                from shared.models import ALL_TABLES  # 延迟 import 避开循环
                with eng.connect() as conn:
                    for tbl in ALL_TABLES:
                        try:
                            r = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
                            out["mysql"]["tables"][tbl] = int(r.scalar() or 0)
                        except Exception as e:
                            out["mysql"]["tables"][tbl] = f"err: {type(e).__name__}"
            except Exception:
                pass
            out["mysql"]["ok"] = True
        except Exception as e:
            out["mysql"]["error"] = f"{type(e).__name__}: {e}"[:200]

    # Redis
    rc = redis_client()
    if rc is not None:
        out["redis"]["enabled"] = True
        try:
            rc.ping()
            out["redis"]["ok"] = True   # ping 成功就算 ok，下面 info / keys 是 best-effort
        except Exception as e:
            out["redis"]["error"] = f"{type(e).__name__}: {e}"[:200]
        # 内存信息（fakeredis 可能不支持，try）
        try:
            info = rc.info("memory")
            if isinstance(info, dict):
                out["redis"]["memory_human"] = info.get("used_memory_human")
        except Exception:
            pass
        # 列出几个我们关心的 key
        try:
            sample_keys = []
            for pattern in ["sync_state:*", "retry_queue", "sync_log:recent"]:
                keys = rc.keys(pattern)
                if keys:
                    sample_keys.extend(list(keys)[:5])
            out["redis"]["keys_sample"] = sample_keys[:10]
        except Exception:
            pass

    return out


def reset_for_test():
    """测试用：清空进程内单例，强迫重新读 env。"""
    global _engine, _session_factory, _redis
    _engine = None
    _session_factory = None
    _redis = None


if __name__ == "__main__":
    # CLI: python3 -m shared.db
    import json
    from shared.env_loader import load_all
    load_all()
    print(json.dumps(health(), ensure_ascii=False, indent=2))
