#!/usr/bin/env python3
"""Redis 双写 + sync_log Redis 镜像测试（用 fakeredis，不依赖真实 Redis）。

覆盖：
- shared.dao.sync_log Redis LPUSH + LTRIM 50
- shared.db.redis_client / health 在没有 REDIS_URL 时降级
- sync_state Redis 双写（如果已实现；后续 Step 6 加）

运行：
    python3 -m shared.tests.test_redis_helpers
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _check(name, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"  {status} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise AssertionError(name)


def _patch_redis_with_fake():
    """把 shared.db._redis 替换成 fakeredis 实例。"""
    import fakeredis
    from shared import db as _db
    fake = fakeredis.FakeRedis(decode_responses=True)
    _db._redis = fake
    return fake


def run_tests():
    print("=== 0. 无 REDIS_URL 降级 ===")
    os.environ.pop("REDIS_URL", None)
    os.environ.pop("MYSQL_DSN", None)
    from shared import db as _db
    _db.reset_for_test()
    _check("redis_client() = None", _db.redis_client() is None)
    _check("is_redis_enabled() = False", _db.is_redis_enabled() is False)

    print("\n=== 1. sync_log Redis 镜像（fakeredis）===")
    _db.reset_for_test()
    fake = _patch_redis_with_fake()

    from shared.dao import sync_log as dao_log
    for i in range(60):
        dao_log._to_redis({
            "script": f"task_{i}", "label": "x", "started_at": "2026-04-28T01:00:00",
            "finished_at": "2026-04-28T01:00:01", "duration_sec": 1.0, "success": True,
        })

    _check("LIST 长度 ltrim 到 50",
           fake.llen(dao_log.REDIS_LIST_KEY) == 50)

    # 最新条在 head（LPUSH 语义）
    head = fake.lindex(dao_log.REDIS_LIST_KEY, 0)
    import json
    head_obj = json.loads(head)
    _check("最新一条在 head", head_obj["script"] == "task_59")

    print("\n=== 2. health() with fakeredis ===")
    h = _db.health()
    _check("redis.enabled = True", h["redis"]["enabled"] is True)
    _check("redis.ok = True", h["redis"]["ok"] is True,
           detail=f"err={h['redis'].get('error')}")
    # memory_human 在 fakeredis 上可能拿不到，宽容处理
    _check("keys_sample 包含 sync_log:recent",
           "sync_log:recent" in (h["redis"]["keys_sample"] or []))

    print("\n=== 3. dao.sync_log 双写（仅 Redis 路径，MySQL 不可用）===")
    fake.delete(dao_log.REDIS_LIST_KEY)
    ok = dao_log.append_sync_log({
        "script": "x", "started_at": "2026-04-28T02:00:00",
        "finished_at": "2026-04-28T02:00:01", "success": True,
    })
    _check("即使 MySQL 不可用，Redis 路径成功 → True", ok is True)
    _check("Redis LIST 多了 1 条", fake.llen(dao_log.REDIS_LIST_KEY) == 1)

    # 清理
    fake.flushdb()
    _db.reset_for_test()

    print("\n🎉 redis_helpers 全部断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
