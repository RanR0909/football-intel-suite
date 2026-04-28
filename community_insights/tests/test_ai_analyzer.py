#!/usr/bin/env python3
"""ai_analyzer 单元测试（mock shared.ai_client.run_task，不发真实请求）。

覆盖：
- _filter_posts：按 competitor + 时间窗过滤
- _persist_result：merge 已有竞品
- analyze 端到端：输入 raw → 调（mock）run_task → 持久化

JSON 解析逻辑已迁移到 shared.ai_client._parse_output（统一管），此处不再覆盖。

运行：
    python3 -m community_insights.tests.test_ai_analyzer
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from community_insights import ai_analyzer


def _check(name, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"  {status} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise AssertionError(name)


def _build_raw_fixture(now_ts: float) -> list:
    return [
        {
            "timestamp": datetime.now().isoformat(),
            "source": "reddit",
            "competitor": "SofaScore",
            "data": {
                "competitor": "SofaScore",
                "posts": [
                    {"post_id": "p1", "subreddit": "soccer", "title": "in window 1",
                     "score": 100, "num_comments": 20,
                     "created_utc": now_ts - 86400 * 1, "comments": []},
                    {"post_id": "p2", "subreddit": "soccer", "title": "in window 2",
                     "score": 50, "num_comments": 5,
                     "created_utc": now_ts - 86400 * 6, "comments": []},
                    {"post_id": "p_old", "subreddit": "soccer", "title": "out of window",
                     "score": 999, "num_comments": 999,
                     "created_utc": now_ts - 86400 * 30, "comments": []},
                ],
            },
        },
        {
            "timestamp": datetime.now().isoformat(),
            "source": "reddit",
            "competitor": "FlashScore",
            "data": {
                "competitor": "FlashScore",
                "posts": [
                    {"post_id": "p3", "subreddit": "soccer", "title": "flash post",
                     "score": 30, "created_utc": now_ts - 86400 * 1, "comments": []},
                ],
            },
        },
    ]


def run_tests():
    print("=== 1. _filter_posts ===")
    now_ts = datetime.now(timezone.utc).timestamp()
    raw = _build_raw_fixture(now_ts)

    sofa_posts = ai_analyzer._filter_posts(raw, "SofaScore", days=7)
    _check("SofaScore 时间窗内 2 条", len(sofa_posts) == 2)
    _check("按 score 倒序", sofa_posts[0]["title"] == "in window 1")
    _check("跨竞品过滤", all(p["title"] != "flash post" for p in sofa_posts))
    _check("FlashScore 独立 1 条", len(ai_analyzer._filter_posts(raw, "FlashScore", days=7)) == 1)
    _check("不存在的竞品空", ai_analyzer._filter_posts(raw, "Nope", days=7) == [])

    print("\n=== 2. _persist_result merge ===")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        original = ai_analyzer.AI_OUTPUT_PATH
        ai_analyzer.AI_OUTPUT_PATH = tmp_dir / "community_ai_analysis.json"
        try:
            ai_analyzer._persist_result("SofaScore", {"alert_level": "low"})
            ai_analyzer._persist_result("FlashScore", {"alert_level": "high"})
            store = json.loads(ai_analyzer.AI_OUTPUT_PATH.read_text(encoding="utf-8"))
            _check("两个竞品共存", set(store.keys()) == {"SofaScore", "FlashScore"})
            _check("FlashScore alert_level", store["FlashScore"]["alert_level"] == "high")

            # 重写 SofaScore，FlashScore 应保留
            ai_analyzer._persist_result("SofaScore", {"alert_level": "medium"})
            store = json.loads(ai_analyzer.AI_OUTPUT_PATH.read_text(encoding="utf-8"))
            _check("SofaScore 已更新", store["SofaScore"]["alert_level"] == "medium")
            _check("FlashScore 未被覆盖", store["FlashScore"]["alert_level"] == "high")
        finally:
            ai_analyzer.AI_OUTPUT_PATH = original

    print("\n=== 3. analyze 端到端 (mock run_task) ===")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        raw_dir = tmp_dir / "raw"
        raw_dir.mkdir()
        raw_path = raw_dir / "reddit_posts.json"
        raw_path.write_text(json.dumps(_build_raw_fixture(now_ts), ensure_ascii=False), encoding="utf-8")

        original_raw = ai_analyzer.RAW_PATH
        original_out = ai_analyzer.AI_OUTPUT_PATH
        original_run_task = ai_analyzer.run_task
        ai_analyzer.RAW_PATH = raw_path
        ai_analyzer.AI_OUTPUT_PATH = tmp_dir / "community_ai_analysis.json"

        # mock run_task — 返回 dict（output_format=json 已经解析过）
        def fake_run_task(task_name, context=None, overrides=None):
            assert task_name == "community_insights"
            assert context and context["competitor"] == "SofaScore"
            return {
                "overall_summary": "mocked summary",
                "sentiment": {"positive": 0.3, "neutral": 0.4, "negative": 0.3},
                "top_topics": ["widgets"],
                "pain_points": ["crash"],
                "opportunities": [],
                "competitor_mentions": ["FlashScore"],
                "representative_quotes": ["sample quote"],
                "alert_level": "medium",
            }
        ai_analyzer.run_task = fake_run_task

        # 测 api_key 检查需要确认环境也清空
        saved_env_keys = {k: os.environ.pop(k, None) for k in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY")}

        try:
            result = ai_analyzer.analyze("SofaScore", days=7, api_key="dummy")
            _check("返回 dict", isinstance(result, dict))
            _check("overall_summary 透传", result["overall_summary"] == "mocked summary")
            _check("alert_level 透传", result["alert_level"] == "medium")
            _check("自动补 generated_at", "generated_at" in result)
            _check("自动补 sample_size = 2", result["sample_size"] == 2)
            _check("自动补 date_range_days = 7", result["date_range_days"] == 7)

            store = json.loads(ai_analyzer.AI_OUTPUT_PATH.read_text(encoding="utf-8"))
            _check("已写入 community_ai_analysis.json", "SofaScore" in store)

            try:
                ai_analyzer.analyze("Fotmob", days=7, api_key="dummy")
                raise AssertionError("应抛 RuntimeError")
            except RuntimeError as e:
                _check("无数据竞品抛 RuntimeError", "无 Reddit 数据" in str(e))

            try:
                ai_analyzer.analyze("SofaScore", days=7, api_key="")
                raise AssertionError("应抛 RuntimeError")
            except RuntimeError as e:
                _check("缺 api_key 抛 RuntimeError", "CLAUDE_API_KEY" in str(e) or "ANTHROPIC_API_KEY" in str(e))

        finally:
            ai_analyzer.RAW_PATH = original_raw
            ai_analyzer.AI_OUTPUT_PATH = original_out
            ai_analyzer.run_task = original_run_task
            for k, v in saved_env_keys.items():
                if v is not None:
                    os.environ[k] = v

    print("\n🎉 全部断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
