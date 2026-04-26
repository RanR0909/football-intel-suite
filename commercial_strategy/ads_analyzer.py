"""Meta 广告投放策略 AI 分析器。

对外暴露 `analyze(competitor, days, api_key) -> dict`：
1. 读 data/async_fb_adlib.json + 调 ads_processor 派生 AdsInfo（与 aggregator 同源）
2. 调 Claude API 生成结构化战略分析
3. 解析 JSON（容错 markdown fence / 前后噪声）
4. 写入 data/ads_ai_analysis.json（merge 已有竞品）

dashboard_server 在 POST /api/ai/ads-strategy 异步触发；
独立运行可用 commercial_strategy/ads_run_headless.py。
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# 允许独立运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from commercial_strategy.ads_processor import process_competitor_ads
from prompts.ads_prompts import build_ads_strategy_prompt

DATA_DIR = _PROJECT_ROOT / "data"
RAW_PATH = DATA_DIR / "async_fb_adlib.json"
AI_OUTPUT_PATH = DATA_DIR / "ads_ai_analysis.json"

CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_TIMEOUT = 120
CLAUDE_MAX_TOKENS = 4096


def _load_raw() -> list:
    if not RAW_PATH.exists():
        return []
    try:
        data = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _filter_competitor_records(raw: list, competitor: str) -> list:
    return [r for r in raw if r.get("competitor") == competitor]


def _call_claude(prompt: str, api_key: str) -> str:
    body = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        CLAUDE_API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=CLAUDE_TIMEOUT, context=ctx) as resp:
        payload = json.loads(resp.read())
    if "content" not in payload or not payload["content"]:
        raise RuntimeError(f"Claude 返回结构异常: {payload}")
    return payload["content"][0]["text"]


def _parse_ai_json(text: str) -> dict:
    """容错 markdown fence 和前后噪声。与 community_insights.ai_analyzer 同步实现。"""
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return json.loads(fence.group(1))
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"AI 输出未含 JSON 对象，原文：{text[:500]}")
    return json.loads(match.group(0))


def _persist_result(competitor: str, result: dict):
    """合并写入 ads_ai_analysis.json，保留其他竞品已有结果。"""
    AI_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    store = {}
    if AI_OUTPUT_PATH.exists():
        try:
            store = json.loads(AI_OUTPUT_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            store = {}
    store[competitor] = result
    AI_OUTPUT_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def analyze(competitor: str, days: int = 7, api_key: str = "") -> dict:
    """触发一次 AI 分析。同步阻塞，~30-60s。

    days 当前未在过滤层使用（fb_adlib 抓的均是 active_status=active），
    保留参数是为了与其他 AI 分析器接口一致 + 未来扩展时按 start_date 过滤。

    Raises:
        RuntimeError: 无 fb_adlib 数据 / Claude 失败 / JSON 解析失败
    """
    if not api_key:
        raise RuntimeError("缺少 CLAUDE_API_KEY")

    records = _filter_competitor_records(_load_raw(), competitor)
    if not records:
        raise RuntimeError(f"{competitor} 暂无 Meta 广告数据，请先运行 fb_adlib 抓取")

    ads_info = process_competitor_ads(records)
    if not ads_info or ads_info.get("active_count", 0) == 0:
        raise RuntimeError(f"{competitor} 抓取记录解析后无有效广告")

    sample_creatives = ads_info.get("top_creatives") or []
    prompt = build_ads_strategy_prompt(competitor, ads_info, sample_creatives)

    text = _call_claude(prompt, api_key)
    result = _parse_ai_json(text)

    # 强制规范字段
    result.setdefault("target_persona", [])
    result.setdefault("value_props", [])
    result.setdefault("geo_focus", [])
    result.setdefault("opportunities", [])
    result.setdefault("risks", [])
    result.setdefault("alert_level", "low")
    result.setdefault("confidence", "medium")
    result["generated_at"] = datetime.now().isoformat()
    result["date_range_days"] = days
    result["sample_size"] = ads_info.get("active_count", 0)

    _persist_result(competitor, result)
    return result
