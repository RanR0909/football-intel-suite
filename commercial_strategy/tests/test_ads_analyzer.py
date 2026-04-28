#!/usr/bin/env python3
"""ads_analyzer 单测（mock shared.ai_client.run_task，不发真实请求）。

覆盖：
- _filter_competitor_records：跨竞品过滤
- _persist_result：merge 已有竞品
- analyze 端到端：raw → process → mock run_task → 持久化

JSON 解析逻辑已迁移到 shared.ai_client._parse_output。

运行：
    python3 -m commercial_strategy.tests.test_ads_analyzer
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

from commercial_strategy import ads_analyzer


def _check(name, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"  {status} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise AssertionError(name)


def _build_raw_fixture(today: datetime) -> list:
    def days_ago(n: int) -> str:
        return (today - timedelta(days=n)).strftime("%Y-%m-%d")
    return [
        {"timestamp": today.isoformat(), "source": "fb_adlib",
         "competitor": "SofaScore", "region": "us",
         "data": {"ad_count": 2, "ads": [
             {"ad_id": "a1", "text": "Live scores live now", "start_date": days_ago(1), "country": "US"},
             {"ad_id": "a2", "text": "VIP unlock advanced stats", "start_date": days_ago(4), "country": "US"},
         ]}},
        {"timestamp": today.isoformat(), "source": "fb_adlib",
         "competitor": "FlashScore", "region": "br",
         "data": {"ad_count": 1, "ads": [
             {"ad_id": "f1", "text": "Apostas e palpites", "start_date": days_ago(2), "country": "BR"},
         ]}},
    ]


def run_tests():
    today = datetime.now(timezone.utc)

    print("=== 1. _filter_competitor_records ===")
    raw = _build_raw_fixture(today)
    _check("SofaScore 1 条 record", len(ads_analyzer._filter_competitor_records(raw, "SofaScore")) == 1)
    _check("FlashScore 1 条 record", len(ads_analyzer._filter_competitor_records(raw, "FlashScore")) == 1)
    _check("不存在竞品空", ads_analyzer._filter_competitor_records(raw, "Nope") == [])

    print("\n=== 2. _persist_result merge ===")
    with tempfile.TemporaryDirectory() as tmp:
        original = ads_analyzer.AI_OUTPUT_PATH
        ads_analyzer.AI_OUTPUT_PATH = Path(tmp) / "ads_ai_analysis.json"
        try:
            ads_analyzer._persist_result("SofaScore", {"alert_level": "low"})
            ads_analyzer._persist_result("FlashScore", {"alert_level": "high"})
            store = json.loads(ads_analyzer.AI_OUTPUT_PATH.read_text(encoding="utf-8"))
            _check("两个竞品共存", set(store.keys()) == {"SofaScore", "FlashScore"})
            _check("FlashScore alert_level", store["FlashScore"]["alert_level"] == "high")
            ads_analyzer._persist_result("SofaScore", {"alert_level": "medium"})
            store = json.loads(ads_analyzer.AI_OUTPUT_PATH.read_text(encoding="utf-8"))
            _check("SofaScore 已更新", store["SofaScore"]["alert_level"] == "medium")
            _check("FlashScore 未被覆盖", store["FlashScore"]["alert_level"] == "high")
        finally:
            ads_analyzer.AI_OUTPUT_PATH = original

    print("\n=== 3. analyze 端到端 (mock run_task) ===")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        raw_path = tmp_dir / "async_fb_adlib.json"
        raw_path.write_text(json.dumps(_build_raw_fixture(today), ensure_ascii=False), encoding="utf-8")

        original_raw = ads_analyzer.RAW_PATH
        original_out = ads_analyzer.AI_OUTPUT_PATH
        original_run_task = ads_analyzer.run_task
        ads_analyzer.RAW_PATH = raw_path
        ads_analyzer.AI_OUTPUT_PATH = tmp_dir / "ads_ai_analysis.json"

        def fake_run_task(task_name, context=None, overrides=None):
            assert task_name == "ads_strategy"
            assert context and context["competitor"] == "SofaScore"
            return {
                "core_strategy": "VIP 转化主导",
                "target_persona": ["美国硬核球迷"],
                "value_props": ["实时比分", "VIP 数据"],
                "geo_focus": ["US"],
                "opportunities": ["对标 VIP 转化漏斗"],
                "risks": ["30 天内可能扩张到 GB"],
                "alert_level": "medium",
                "confidence": "high",
            }
        ads_analyzer.run_task = fake_run_task

        # 清空环境 key 让"缺 key"用例能命中
        saved_env_keys = {k: os.environ.pop(k, None) for k in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY")}

        try:
            result = ads_analyzer.analyze("SofaScore", days=7, api_key="dummy")
            _check("返回 dict", isinstance(result, dict))
            _check("core_strategy 透传", result["core_strategy"] == "VIP 转化主导")
            _check("alert_level 透传", result["alert_level"] == "medium")
            _check("confidence 透传", result["confidence"] == "high")
            _check("自动补 generated_at", "generated_at" in result)
            _check("sample_size = active_count = 2", result["sample_size"] == 2)

            store = json.loads(ads_analyzer.AI_OUTPUT_PATH.read_text(encoding="utf-8"))
            _check("已写入 ads_ai_analysis.json", "SofaScore" in store)

            try:
                ads_analyzer.analyze("Fotmob", days=7, api_key="dummy")
                raise AssertionError("应抛 RuntimeError")
            except RuntimeError as e:
                _check("无数据竞品抛 RuntimeError", "无 Meta 广告数据" in str(e))

            try:
                ads_analyzer.analyze("SofaScore", days=7, api_key="")
                raise AssertionError("应抛 RuntimeError")
            except RuntimeError as e:
                _check("缺 api_key 抛 RuntimeError",
                       "CLAUDE_API_KEY" in str(e) or "ANTHROPIC_API_KEY" in str(e))

        finally:
            ads_analyzer.RAW_PATH = original_raw
            ads_analyzer.AI_OUTPUT_PATH = original_out
            ads_analyzer.run_task = original_run_task
            for k, v in saved_env_keys.items():
                if v is not None:
                    os.environ[k] = v

    print("\n🎉 全部断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
