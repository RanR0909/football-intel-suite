#!/usr/bin/env python3
"""retry_queue 单元测试（不依赖外部 API；用 tempfile 隔离队列文件）。

覆盖：
- enqueue 新条目 / 同名合并 / 永久失败 kind 不入队
- update_retry 退避递增 / 达上限自动清除
- due_items 时间窗筛选
- remove / remove_by_script
- snapshot / clear

运行：
    python3 -m shared.tests.test_retry_queue
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared import retry_queue


def _check(name, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"  {status} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise AssertionError(name)


def _swap_path(tmp_dir: Path):
    """把 retry_queue 写到 tmp，不污染真实数据。返回还原函数。"""
    original = retry_queue.QUEUE_PATH
    retry_queue.QUEUE_PATH = tmp_dir / "retry_queue.json"
    return lambda: setattr(retry_queue, "QUEUE_PATH", original)


def run_tests():
    with tempfile.TemporaryDirectory() as tmp:
        restore = _swap_path(Path(tmp))
        try:
            print("=== 1. enqueue 基本路径 ===")
            retry_queue.clear()
            i1 = retry_queue.enqueue("foo", "boom", "timeout")
            _check("入队成功，返回 id", i1 is not None and len(i1) == 12)

            snap = retry_queue.snapshot()
            _check("队列有 1 条", len(snap["items"]) == 1)
            _check("attempts=1", snap["items"][0]["attempts"] == 1)
            _check("有 retry_after", "retry_after" in snap["items"][0])
            _check("kind 透传", snap["items"][0]["last_kind"] == "timeout")

            print("\n=== 2. 同名 script 合并 ===")
            i2 = retry_queue.enqueue("foo", "boom2", "timeout")
            _check("返回相同 id", i2 == i1)
            snap = retry_queue.snapshot()
            _check("仍只有 1 条", len(snap["items"]) == 1)
            _check("attempts 递增到 2", snap["items"][0]["attempts"] == 2)
            _check("last_error 已更新", snap["items"][0]["last_error"] == "boom2")

            print("\n=== 3. 永久失败 kind 不入队 ===")
            retry_queue.clear()
            ip = retry_queue.enqueue("bar", "cookie expired", "login_required")
            _check("login_required 返回 None", ip is None)
            _check("队列仍为空", len(retry_queue.snapshot()["items"]) == 0)

            print("\n=== 4. update_retry 触达 max_attempts ===")
            retry_queue.clear()
            i = retry_queue.enqueue("zz", "first fail", "timeout")
            for _ in range(5):
                retry_queue.update_retry(i, "still bad", "timeout")
            snap = retry_queue.snapshot()
            _check("达上限被驱逐", all(it["id"] != i for it in snap["items"]))

            print("\n=== 5. update_retry 永久失败 kind 也驱逐 ===")
            retry_queue.clear()
            i = retry_queue.enqueue("aa", "first fail", "timeout")
            res = retry_queue.update_retry(i, "now login required", "login_required")
            _check("update 返回 None（永久失败）", res is None)
            _check("队列已清空", len(retry_queue.snapshot()["items"]) == 0)

            print("\n=== 6. due_items 时间筛选 ===")
            retry_queue.clear()
            i_old = retry_queue.enqueue("old_one", "x", "timeout")
            i_new = retry_queue.enqueue("new_one", "x", "timeout")
            # 把 old_one 的 retry_after 改到过去
            data = json.loads(retry_queue.QUEUE_PATH.read_text(encoding="utf-8"))
            for it in data["items"]:
                if it["id"] == i_old:
                    it["retry_after"] = "2020-01-01T00:00:00+00:00"
            retry_queue.QUEUE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            due = retry_queue.due_items()
            _check("只有 old_one 到期", len(due) == 1 and due[0]["id"] == i_old)

            print("\n=== 7. remove / remove_by_script ===")
            ok = retry_queue.remove(i_old)
            _check("remove 找到并删除", ok is True)
            _check("队列剩 1 条", len(retry_queue.snapshot()["items"]) == 1)

            ok2 = retry_queue.remove_by_script("new_one")
            _check("remove_by_script 成功", ok2 is True)
            _check("队列空", len(retry_queue.snapshot()["items"]) == 0)

            ok3 = retry_queue.remove("nonexistent_id")
            _check("不存在 id 返回 False", ok3 is False)

            print("\n=== 8. clear / snapshot ===")
            retry_queue.enqueue("x", "y", "timeout")
            retry_queue.enqueue("z", "y", "timeout")
            _check("snapshot 反映 2 条", len(retry_queue.snapshot()["items"]) == 2)
            retry_queue.clear()
            _check("clear 后空", len(retry_queue.snapshot()["items"]) == 0)

            print("\n=== 9. 退避递增 ===")
            retry_queue.clear()
            i = retry_queue.enqueue("backoff_test", "fail", "timeout")
            t1 = datetime.fromisoformat(retry_queue.snapshot()["items"][0]["retry_after"])
            retry_queue.update_retry(i, "fail2", "timeout")
            t2 = datetime.fromisoformat(retry_queue.snapshot()["items"][0]["retry_after"])
            _check("第二次重试时间晚于第一次", t2 > t1, f"{t1} → {t2}")
            retry_queue.update_retry(i, "fail3", "timeout")
            t3 = datetime.fromisoformat(retry_queue.snapshot()["items"][0]["retry_after"])
            _check("第三次更晚", t3 > t2)

        finally:
            restore()

    print("\n🎉 retry_queue 全部断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
