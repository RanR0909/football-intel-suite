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
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 允许独立运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.ai_client import run_task

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

DATA_DIR = _PROJECT_ROOT / "data"
RAW_PATH = DATA_DIR / "raw" / "reddit_posts.json"
AI_OUTPUT_PATH = DATA_DIR / "community_ai_analysis.json"


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
    if not (api_key or os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        raise RuntimeError("缺少 CLAUDE_API_KEY / ANTHROPIC_API_KEY")

    posts = _filter_posts(_load_raw(), competitor, days)
    if not posts:
        raise RuntimeError(f"{competitor} 在近 {days} 天内无 Reddit 数据，请先运行抓取")

    # run_task("community_insights") → 返回 dict（output_format=json + json_strip_markdown=true）
    result = run_task("community_insights", context={
        "competitor": competitor,
        "posts": posts,
        "days": days,
    })
    if not isinstance(result, dict) or result.get("_parse_error"):
        raise RuntimeError(f"AI 输出 JSON 解析失败：{result if isinstance(result, dict) else str(result)[:200]}")

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
