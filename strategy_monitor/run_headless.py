#!/usr/bin/env python3
"""
Headless runner for strategy_monitor — exports JSON to root /data/
without launching the Streamlit UI.
Uses Claude Haiku via flashapi proxy for AI analysis.
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy_monitor import (
    get_all_apps, load_state, save_state,
    fetch_app_data, compute_diff, analyze_with_ai,
    CLAUDE_API_KEY,
)

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"


def export_json(results: list) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "strategy_monitor.json"

    data = {
        "generated_at": datetime.now().isoformat(),
        "total_monitored": len(results),
        "changes_detected": sum(1 for r in results if "error" not in r and r["diff"]["has_changed"]),
        "competitors": {}
    }

    for r in results:
        name = r["name"]
        if "error" in r:
            data["competitors"][name] = {"error": r["error"]}
            continue

        diff = r["diff"]
        entry = {
            "version": r["current_data"]["version"],
            "release_notes": r["current_data"]["release_notes"],
            "release_date": r["current_data"].get("release_date", ""),
            "in_app_purchases": r["current_data"]["in_app_purchases"],
            "has_changed": diff["has_changed"],
            "is_first_record": diff["is_first_record"],
            "version_changed": diff["version_changed"],
            "iap_changed": diff["iap_changed"],
            "changes": diff["changes"],
        }
        if "analysis" in r:
            entry["analysis"] = r["analysis"]
        data["competitors"][name] = entry

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据已导出: {out_path}")


def main():
    if not CLAUDE_API_KEY:
        print("错误: 未设置 CLAUDE_API_KEY 环境变量。")
        sys.exit(1)

    print("=" * 60)
    print(f"策略监控 (Headless) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    all_apps = get_all_apps()
    state = load_state()
    results = []

    for name in all_apps:
        print(f"\n[抓取] {name} ...")
        try:
            current_data = fetch_app_data(name)
            diff = compute_diff(name, current_data, state)
            state[name] = {
                "version": current_data["version"],
                "in_app_purchases": current_data["in_app_purchases"],
            }
            results.append({"name": name, "current_data": current_data, "diff": diff})
        except Exception as e:
            print(f"  !! 失败: {e}")
            results.append({"name": name, "error": str(e), "diff": {"has_changed": False, "changes": []}})

    save_state(state)

    changed_results = [r for r in results if "error" not in r and r["diff"]["has_changed"]]
    if changed_results:
        print(f"\n[AI 分析] {len(changed_results)} 个竞品有变更，正在分析...")
        for r in changed_results:
            print(f"  [分析] {r['name']} ...")
            r["analysis"] = analyze_with_ai(
                app_name=r["name"],
                changes=r["diff"]["changes"],
                release_notes=r["current_data"]["release_notes"],
                in_app_purchases=r["current_data"]["in_app_purchases"],
            )

    export_json(results)

    changed = sum(1 for r in results if "error" not in r and r["diff"]["has_changed"])
    print(f"\n完成 — 检测到 {changed} 个竞品有变化")


if __name__ == "__main__":
    main()
