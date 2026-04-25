#!/usr/bin/env python3
"""
Headless runner for market_rank — exports JSON to root /data/
without launching the Streamlit UI.
"""

import os
import sys
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import core functions directly (skip Streamlit)
from market_rank import (
    fetch_top_free_sports, build_known_apps, load_ranking_history,
    save_ranking_history, get_today_key, get_yesterday_key,
    compute_delta, is_known_app, get_competitor_rank,
    detect_new_contenders, detect_fast_movers, generate_ai_market_brief,
    aggregate_market_data, save_market_csv, compute_baseline_comparison,
    get_market_rank_targets,
    COMPETITORS, DATA_DIR, BASELINE_APP, BASELINE_LABEL,
)


def export_json(today_ranking: list[dict], history: dict, known_apps: dict,
                new_contenders: list[dict], fast_movers: list[dict],
                ai_brief: Optional[str],
                multi_source_data: Optional[dict] = None) -> None:
    """Export structured JSON to root /data/ for the main dashboard."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "market_rank.json"

    today_key = get_today_key()
    yesterday_key = get_yesterday_key()

    competitor_performance = {}
    for comp_name, comp_info in COMPETITORS.items():
        app_id = str(comp_info["app_id"])
        rank = get_competitor_rank(today_ranking, app_id)
        if rank is not None:
            delta_val = compute_delta(history, today_key, yesterday_key, app_id, rank)
            competitor_performance[comp_name] = {
                "rank": rank,
                "delta": delta_val,
                "app_id": app_id,
            }
        else:
            competitor_performance[comp_name] = {
                "rank": None,
                "delta": None,
                "app_id": app_id,
            }

    leaderboard = []
    for app in today_ranking:
        app_id = app["app_id"]
        delta_val = compute_delta(history, today_key, yesterday_key, app_id, app["rank"])
        leaderboard.append({
            "rank": app["rank"],
            "name": app["name"],
            "app_id": app_id,
            "artist": app["artist"],
            "delta": delta_val,
            "is_known": is_known_app(known_apps, app_id, app["name"]),
        })

    data = {
        "generated_at": datetime.now().isoformat(),
        "date": today_key,
        "total_apps": len(today_ranking),
        "competitor_performance": competitor_performance,
        "new_contenders": [
            {"rank": a["rank"], "name": a["name"], "artist": a["artist"], "delta": a.get("delta")}
            for a in new_contenders
        ],
        "fast_movers": [
            {"rank": a["rank"], "name": a["name"], "delta": a["delta"], "artist": a["artist"]}
            for a in fast_movers
        ],
        "ai_brief": ai_brief,
        "leaderboard": leaderboard,
    }

    if multi_source_data:
        data["multi_source"] = multi_source_data
        data["baseline_app"] = BASELINE_APP
        data["baseline_label"] = BASELINE_LABEL
        data["baseline_comparison"] = compute_baseline_comparison(
            [
                {
                    "app": app_name,
                    "rank": ms.get("metrics", {}).get("rank"),
                    "download_proxy": ms.get("metrics", {}).get("downloads"),
                    "rating_growth": ms.get("metrics", {}).get("rating_growth"),
                    "revenue_proxy": ms.get("metrics", {}).get("revenue_proxy"),
                    "sentiment_score": ms.get("metrics", {}).get("sentiment_score"),
                    "update_frequency": ms.get("metrics", {}).get("update_frequency"),
                    "_raw": ms.get("_raw", {}),
                }
                for app_name, ms in multi_source_data.items()
            ]
        )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据已导出: {out_path}")


def main():
    print("=" * 60)
    print(f"市场排名 (Headless) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    known_apps = build_known_apps()
    history = load_ranking_history()
    today_key = get_today_key()
    yesterday_key = get_yesterday_key()

    print("[抓取] App Store Top 100 ...")
    today_ranking = fetch_top_free_sports()
    print(f"  获取到 {len(today_ranking)} 个应用")

    # Store today's ranking
    today_data = {app["app_id"]: app["rank"] for app in today_ranking}
    history[today_key] = today_data
    save_ranking_history(history)

    # Detect alerts
    new_contenders = detect_new_contenders(today_ranking, history, today_key)
    fast_movers = detect_fast_movers(today_ranking, history, today_key, yesterday_key)

    if new_contenders:
        print(f"[新晋竞争者] {len(new_contenders)} 个")
    if fast_movers:
        print(f"[快速上升] {len(fast_movers)} 个")

    # AI brief
    ai_brief = generate_ai_market_brief(new_contenders, fast_movers)
    if ai_brief:
        print("[AI 简报] 已生成")

    # Multi-source data collection (Androidrank + Sensor Tower + Store + Reddit)
    print("\n[多源数据] 抓取竞品详细数据...")
    records = aggregate_market_data(get_market_rank_targets())
    print(f"[多源数据] 完成，覆盖 {len(records)} 个竞品")

    # Save to CSV for historical trend analysis
    save_market_csv(records)

    # Build multi_source dict for JSON export (keyed by app name)
    multi_source_data = {}
    for rec in records:
        name = rec["app"]
        metrics = {
            "rank": rec.get("rank"),
            "downloads": rec.get("download_proxy"),
            "rating_count": None,
            "rating_growth": rec.get("rating_growth"),
            "review_count": None,
            "sentiment_score": rec.get("sentiment_score"),
            "update_frequency": rec.get("update_frequency"),
            "revenue_proxy": rec.get("revenue_proxy"),
        }
        raw = rec.get("_raw", {})
        st_data = raw.get("sensor_tower", {}) if isinstance(raw, dict) else {}
        ar = raw.get("androidrank", {}) if isinstance(raw, dict) else {}
        store = raw.get("store", {}) if isinstance(raw, dict) else {}
        gp = store.get("gp", {}) if isinstance(store, dict) else {}
        ios = store.get("ios", {}) if isinstance(store, dict) else {}
        metrics["rating_count"] = (
            st_data.get("rating_count")
            or ar.get("total_ratings")
            or gp.get("ratings")
            or ios.get("ratings")
        )
        metrics["review_count"] = gp.get("reviews_count")
        multi_source_data[name] = {
            "app": name,
            "metrics": metrics,
            "timestamp": rec.get("timestamp"),
            "_raw": rec.get("_raw", {}),
        }

    export_json(today_ranking, history, known_apps, new_contenders, fast_movers, ai_brief, multi_source_data)
    print("完成")


if __name__ == "__main__":
    main()
