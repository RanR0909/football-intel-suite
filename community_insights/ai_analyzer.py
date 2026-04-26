"""社媒舆情 AI 分析器。

对外暴露 `analyze(competitor, days, api_key) -> dict`：
1. 读 data/raw/reddit_posts.json，按 competitor + 时间窗过滤
2. 调 Claude API 生成结构化分析
3. 解析 JSON（容错 markdown 包裹 / 前后噪声）
4. 写入 data/community_ai_analysis.json（merge 已有竞品）

dashboard_server 在 POST /api/ai/community-insights 回调；
独立运行可用 community_insights/run_headless.py。
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 允许独立运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from prompts.community_prompts import build_community_insights_prompt

# ---------------------------------------------------------------------------
# 路径与外部 API
# ---------------------------------------------------------------------------

DATA_DIR = _PROJECT_ROOT / "data"
RAW_PATH = DATA_DIR / "raw" / "reddit_posts.json"
AI_OUTPUT_PATH = DATA_DIR / "community_ai_analysis.json"

CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_TIMEOUT = 120
CLAUDE_MAX_TOKENS = 4096


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _load_raw() -> list:
    if not RAW_PATH.exists():
        return []
    try:
        data = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _filter_posts(raw: list, competitor: str, days: int) -> list:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    out = []
    for rec in raw:
        if rec.get("competitor") != competitor:
            continue
        for p in (rec.get("data", {}) or {}).get("posts") or []:
            if (p.get("created_utc") or 0) >= cutoff:
                out.append(p)
    out.sort(key=lambda x: x.get("score", 0), reverse=True)
    return out


def _call_claude(prompt: str, api_key: str) -> str:
    """直接走 urllib（与 commercial_strategy.call_claude 一致风格，不引入 requests 依赖）。"""
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
    """从 Claude 输出抽出第一个 JSON 对象，容错 ```json 包裹和前后噪声。"""
    # 优先剥离 markdown fence
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return json.loads(fence.group(1))
    # 否则抓第一个 {...} 大括号块
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"AI 输出未含 JSON 对象，原文：{text[:500]}")
    return json.loads(match.group(0))


def _persist_result(competitor: str, result: dict):
    """合并写入 community_ai_analysis.json，保留其他竞品已有结果。"""
    AI_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    store = {}
    if AI_OUTPUT_PATH.exists():
        try:
            store = json.loads(AI_OUTPUT_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            store = {}
    store[competitor] = result
    AI_OUTPUT_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def analyze(competitor: str, days: int = 7, api_key: str = "") -> dict:
    """触发一次 AI 分析。同步阻塞，~30-60s。

    Raises:
        RuntimeError: 无 Reddit 数据可分析 / Claude API 调用失败 / JSON 解析失败
    """
    if not api_key:
        raise RuntimeError("缺少 CLAUDE_API_KEY")

    posts = _filter_posts(_load_raw(), competitor, days)
    if not posts:
        raise RuntimeError(f"{competitor} 在近 {days} 天内无 Reddit 数据，请先运行抓取")

    prompt = build_community_insights_prompt(competitor, posts, days=days)
    text = _call_claude(prompt, api_key)
    result = _parse_ai_json(text)

    # 强制规范字段（缺失项填默认）
    result.setdefault("sentiment", {})
    result.setdefault("top_topics", [])
    result.setdefault("pain_points", [])
    result.setdefault("opportunities", [])
    result.setdefault("competitor_mentions", [])
    result.setdefault("representative_quotes", [])
    result.setdefault("alert_level", "low")
    result["generated_at"] = datetime.now().isoformat()
    result["date_range_days"] = days
    result["sample_size"] = len(posts)

    _persist_result(competitor, result)
    return result
