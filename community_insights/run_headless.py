#!/usr/bin/env python3
"""社媒舆情 AI 分析 CLI 入口。

用法：
    python -m community_insights.run_headless SofaScore --days 7
    python community_insights/run_headless.py SofaScore --days 7

需要环境变量 CLAUDE_API_KEY；通常由 dashboard_server 的 POST /api/ai/community-insights
异步触发，命令行模式主要用于单次手动调试 / 排查 prompt。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 允许独立运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from community_insights.ai_analyzer import analyze


def main() -> int:
    parser = argparse.ArgumentParser(description="社媒舆情 AI 分析（Reddit）")
    parser.add_argument("competitor", help="竞品名（必须与 competitors.json 中一致）")
    parser.add_argument("--days", type=int, default=7, help="时间窗（天），默认 7")
    parser.add_argument("--api-key", default=None, help="Claude API Key（默认读 CLAUDE_API_KEY 环境变量）")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("CLAUDE_API_KEY", "")
    if not api_key:
        print("[ERROR] 缺少 CLAUDE_API_KEY，环境变量未设置且未传 --api-key", file=sys.stderr)
        return 2

    try:
        result = analyze(args.competitor, days=args.days, api_key=api_key)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[OK] 已写入 data/community_ai_analysis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
