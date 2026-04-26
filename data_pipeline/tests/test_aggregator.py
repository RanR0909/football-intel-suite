#!/usr/bin/env python3
"""聚合层回归测试。

用 fixture 验证非空路径下：
- 字段映射正确
- 4 类预警规则正确触发
- views 切片（by_region / by_label / timeline）正确生成
- metrics 计算正确
- 跨数据源的字段合并（如 ranking_history → delta_wow，detail → deep_analysis）

不引入 pytest 依赖，直接用 assert。运行：
    python3 -m data_pipeline.tests.test_aggregator
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# 允许独立脚本运行
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data_pipeline import aggregator


# ---------------------------------------------------------------------------
# Fixture 构建
# ---------------------------------------------------------------------------

def _write(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_fixtures(data_dir: Path):
    """造覆盖所有 4 类预警 + 4 类 timeline 事件的 fixture。"""

    competitors = {
        "SofaScore":   {"gp": "com.sofascore.results", "ios": 1176147574, "app_id": "1176147574", "bundle_id": "x"},
        "FlashScore":  {"gp": "com.flashscore.app",    "ios": 766443283,  "app_id": "766443283",  "bundle_id": "x"},
        "OneFootball": {"gp": "com.onefootball",       "ios": 382002079,  "app_id": "382002079",  "bundle_id": "x"},
        "365Scores":   {"gp": "com.scores365",         "ios": 571801488,  "app_id": "571801488",  "bundle_id": "x"},
        "Fotmob":      {"gp": "com.fotmob",            "ios": 488575683,  "app_id": "488575683",  "bundle_id": "x"},
        "LiveScore":   {"gp": "com.livescore",         "ios": 356928178,  "app_id": "356928178",  "bundle_id": "x"},
    }
    regions = {
        "us": {"label": "美国", "lang": "en"},
        "jp": {"label": "日本", "lang": "ja"},
        "br": {"label": "巴西", "lang": "pt"},
    }
    _write(data_dir / "competitors.json", competitors)
    _write(data_dir / "regions.json", regions)

    # ---- strategy_monitor.json：SofaScore 版本更新含功能关键词 ----
    _write(data_dir / "strategy_monitor.json", {
        "generated_at": datetime.now().isoformat(),
        "total_monitored": 6,
        "changes_detected": 1,
        "competitors": {
            "SofaScore": {
                "version": "25.4.1",
                "release_notes": "redesigned widgets and added AI insight panel",
                "in_app_purchases": [{"note": "Premium $4.99"}],
                "has_changed": True,
                "is_first_record": False,
                "version_changed": True,
                "iap_changed": False,
                "changes": ["新增 AI 洞察面板", "Widgets 重设计", "Multiview 体验升级"],
                "analysis": "SofaScore 此次重在数据洞察",
            },
            "FlashScore": {
                "version": "9.10",
                "release_notes": "minor bug fixes",
                "has_changed": False,
                "is_first_record": False,
                "version_changed": False,
                "iap_changed": False,
                "changes": [],
            },
            "Fotmob": {"error": "store fetch failed"},
        },
    })

    # ---- market_rank.json：FlashScore 当日上升 ----
    _write(data_dir / "market_rank.json", {
        "generated_at": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_apps": 100,
        "competitor_performance": {
            "SofaScore":   {"rank": 12, "delta": -2, "app_id": "1176147574"},
            "FlashScore":  {"rank": 5,  "delta": 8,  "app_id": "766443283"},
            "OneFootball": {"rank": 28, "delta": 0,  "app_id": "382002079"},
            "365Scores":   {"rank": 41, "delta": -1, "app_id": "571801488"},
            "Fotmob":      {"rank": 33, "delta": 1,  "app_id": "488575683"},
            "LiveScore":   {"rank": 50, "delta": 0,  "app_id": "356928178"},
        },
        "fast_movers": [{"rank": 5, "name": "FlashScore", "delta": 8, "artist": "Livesport"}],
        "new_contenders": [],
        "ai_brief": "FlashScore 本日上升明显",
        "leaderboard": [
            {"rank": 5, "name": "FlashScore", "app_id": "766443283", "artist": "Livesport", "delta": 8, "is_known": True},
        ],
        "baseline_app": "AllFootball",
        "baseline_label": "All Football",
    })

    # ---- ranking_history.json：构造一周前 vs 今日的快照让 FlashScore delta_wow=15 ----
    today = datetime.now()
    week_ago = today - timedelta(days=7)
    _write(data_dir / "ranking_history.json", {
        week_ago.strftime("%Y-%m-%d"): {
            "1176147574": 14,   # SofaScore 14 → 12 = +2
            "766443283":  20,   # FlashScore 20 → 5 = +15  ⚡ 触发 rank_rise alert
            "382002079":  29,   # OneFootball 29 → 28
        },
        today.strftime("%Y-%m-%d"): {
            "1176147574": 12,
            "766443283":  5,
            "382002079":  28,
        },
    })

    # ---- competitor_comments.json：SofaScore 在 us/jp 都有低星评论 ----
    _write(data_dir / "competitor_comments.json", {
        "generated_at": datetime.now().isoformat(),
        "date": today.strftime("%Y-%m-%d"),
        "competitors": {
            "SofaScore": {
                "regions": {
                    "us": {
                        "count": 30, "negative_count": 18,
                        "labels": {"[问题抱怨]": 10, "[流失信号]": 5, "[正向反馈]": 3},
                        "summary": "",
                        "reviews": [{"score": 1, "version": "25.4.1", "label": "[问题抱怨]", "content": "crashes a lot"}],
                    },
                    "jp": {
                        "count": 12, "negative_count": 6,
                        "labels": {"[问题抱怨]": 4, "[竞品对比]": 2},
                        "summary": "",
                        "reviews": [],
                    },
                },
            },
            "FlashScore": {
                "regions": {
                    "br": {
                        "count": 8, "negative_count": 0,
                        "labels": {"[正向反馈]": 6, "[高价值功能请求]": 2},
                        "summary": "",
                        "reviews": [],
                    },
                },
            },
        },
    })

    # ---- weekly_review.json ----
    _write(data_dir / "weekly_review.json", {
        "summary": "本周 SofaScore 在美国市场出现明显负面信号",
        "localization_insight": "巴西用户对 FlashScore 的足球数据展示满意度高",
        "per_competitor": {
            "SofaScore":  {"total": 42, "regions": {"us": {"count": 30, "labels": {}}}},
            "FlashScore": {"total": 8,  "regions": {"br": {"count": 8,  "labels": {}}}},
        },
        "total_reviews": 50,
        "label_distribution": {"[问题抱怨]": 14},
        "platform_distribution": {"App Store": 30, "Google Play": 20},
        "region_distribution": {"美国": 30, "日本": 12, "巴西": 8},
        "feature_keywords": {"crash": 8, "lineup": 3},
        "localization_review_count": 5,
        "localization_by_region": {"巴西": 3, "日本": 2},
        "generated_at": datetime.now().isoformat(),
        "competitors": {},
        "days_analyzed": 7,
    })

    # ---- competitor_detail_SofaScore.json：填 deep_analysis ----
    _write(data_dir / "competitor_detail_SofaScore.json", {
        "competitor": "SofaScore",
        "generated_at": datetime.now().isoformat(),
        "days_analyzed": 7,
        "total_reviews": 42,
        "regions": {},
        "feature_analysis": {
            "summary": "SofaScore 用户对新版 Widgets 和 AI 洞察反馈两极",
            "total_reviews": 42,
            "label_distribution": {"[问题抱怨]": 14},
            "platform_distribution": {},
            "region_distribution": {},
            "feature_keywords": {"widget": 10, "AI": 6},
            "feature_review_count": 16,
        },
    })

    # ---- commercial_strategy.json：OneFootball 博彩信号 + SofaScore 价格变动 ----
    _write(data_dir / "commercial_strategy.json", {
        "generated_at": datetime.now().isoformat(),
        "competitors": {
            "SofaScore": {
                "monetization_tags": ["Subscription Heavy"],
                "iap_items": [{"name": "Premium", "price_usd": 5.99, "currency": "USD", "category": "订阅"}],
                "price_alerts": [{"name": "Premium", "direction": "涨价", "prev": 4.99, "curr": 5.99, "delta": 1.0}],
                "iap_changes": [{"name": "Stat Pack", "type": "新增"}],
                "rpd_index": 1.42,
                "rank": 12,
                "betting_signals": False,
                "description_keywords": [],
                "seller_url": "https://example.com",
                "ai_intent": "强化订阅",
            },
            "OneFootball": {
                "monetization_tags": ["Ad-Driven"],
                "iap_items": [],
                "price_alerts": [],
                "iap_changes": [],
                "rpd_index": 0.6,
                "rank": 28,
                "betting_signals": True,
                "description_keywords": ["odds", "betting"],
                "seller_url": "https://example.com",
                "ai_intent": "广告 + 博彩导流",
            },
        },
    })

    # ---- commercial_weekly.json ----
    _write(data_dir / "commercial_weekly.json", {
        "summary": "本周观察到 SofaScore 提价 20%、OneFootball 加大博彩导流",
        "generated_at": datetime.now().isoformat(),
        "period": "7d",
        "dates_covered": [today.strftime("%Y-%m-%d")],
    })

    # ---- data/raw/reddit_posts.json：构造时间窗内 + 窗口外 + 评论 ----
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    now_ts = today.timestamp()
    in_window_1 = now_ts - 86400 * 1            # 1 天前
    in_window_2 = now_ts - 86400 * 5            # 5 天前
    out_of_window = now_ts - 86400 * 30         # 30 天前 → 应被过滤
    _write(raw_dir / "reddit_posts.json", [
        {
            "timestamp": today.isoformat(),
            "source": "reddit",
            "competitor": "SofaScore",
            "data": {
                "competitor": "SofaScore",
                "posts": [
                    {
                        "post_id": "p1", "subreddit": "soccer", "title": "SofaScore widget broken",
                        "selftext": "stats not updating", "url": "https://reddit.com/r/soccer/comments/p1",
                        "score": 120, "num_comments": 45, "created_utc": in_window_1, "upvote_ratio": 0.9,
                        "comments": [
                            {"body": "Same here", "score": 12, "created_utc": in_window_1},
                            {"body": "FlashScore is better now", "score": 8, "created_utc": in_window_1},
                        ],
                    },
                    {
                        "post_id": "p2", "subreddit": "footballmanagergames", "title": "SofaScore vs Fotmob",
                        "selftext": "", "url": "https://reddit.com/r/fmgames/comments/p2",
                        "score": 45, "num_comments": 10, "created_utc": in_window_2, "upvote_ratio": 0.8,
                        "comments": [],
                    },
                    {
                        "post_id": "p3_old", "subreddit": "soccer", "title": "old post",
                        "score": 999, "num_comments": 999, "created_utc": out_of_window,
                        "comments": [],
                    },
                ],
            },
        },
        {
            "timestamp": today.isoformat(),
            "source": "reddit",
            "competitor": "FlashScore",
            "data": {
                "competitor": "FlashScore",
                "posts": [
                    {
                        "post_id": "p4", "subreddit": "soccer", "title": "FlashScore is fast",
                        "score": 30, "num_comments": 5, "created_utc": in_window_1,
                        "comments": [],
                    },
                ],
            },
        },
    ])

    # ---- data/community_ai_analysis.json：仅 SofaScore 已生成 AI ----
    _write(data_dir / "community_ai_analysis.json", {
        "SofaScore": {
            "overall_summary": "SofaScore 用户主要抱怨 widgets 和数据更新延迟。",
            "sentiment": {"positive": 0.2, "neutral": 0.3, "negative": 0.5},
            "top_topics": ["widget", "stats update"],
            "pain_points": ["widget broken", "stats not updating"],
            "opportunities": ["faster realtime stats"],
            "competitor_mentions": ["FlashScore", "Fotmob"],
            "representative_quotes": ["stats not updating", "FlashScore is better now"],
            "alert_level": "medium",
            "generated_at": today.isoformat(),
            "date_range_days": 7,
            "sample_size": 2,
        },
    })


# ---------------------------------------------------------------------------
# 断言
# ---------------------------------------------------------------------------

def _check(name: str, cond: bool, detail: str = ""):
    status = "✅" if cond else "❌"
    print(f"  {status} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise AssertionError(name)


def run_tests():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _build_fixtures(tmp_dir)

        # monkey-patch DATA_DIR / RAW_DIR / OUTPUT_PATH
        original_data_dir = aggregator.DATA_DIR
        original_raw_dir = aggregator.RAW_DIR
        original_output = aggregator.OUTPUT_PATH
        aggregator.DATA_DIR = tmp_dir
        aggregator.RAW_DIR = tmp_dir / "raw"
        aggregator.OUTPUT_PATH = tmp_dir / "dashboard_data.json"
        try:
            data = aggregator.build_dashboard_data()
            payload = aggregator.to_dict(data)
        finally:
            aggregator.DATA_DIR = original_data_dir
            aggregator.RAW_DIR = original_raw_dir
            aggregator.OUTPUT_PATH = original_output

        comps = payload["competitors"]
        sofa = comps["SofaScore"]
        flash = comps["FlashScore"]
        one = comps["OneFootball"]
        fotmob = comps["Fotmob"]

        print("\n=== 1. 竞品骨架 ===")
        _check("六个竞品全部初始化", set(comps.keys()) == {"SofaScore", "FlashScore", "OneFootball", "365Scores", "Fotmob", "LiveScore"})
        _check("竞品颜色正确", sofa["color"] == "#7b6ef6")
        _check("ios_id 透传", sofa["ios_id"] == "1176147574")
        _check("android_id 透传", sofa["android_id"] == "com.sofascore.results")

        print("\n=== 2. Rank 数据 ===")
        _check("rank.current 来自 market_rank", flash["rank"]["current"] == 5)
        _check("rank.delta_dod 来自 market_rank", flash["rank"]["delta_dod"] == 8)
        _check("rank.delta_wow 由 ranking_history 计算 = 15", flash["rank"]["delta_wow"] == 15, f"got {flash['rank']['delta_wow']}")
        _check("rank.fast_mover 标记", flash["rank"]["fast_mover"] is True)
        _check("rank.history 至少含两个日期", len(flash["rank"]["history"]) == 2)

        print("\n=== 3. Version 数据 ===")
        _check("version.current", sofa["version"]["current"] == "25.4.1")
        _check("version.has_changed", sofa["version"]["has_changed"] is True)
        _check("version.changes 列表", len(sofa["version"]["changes"]) == 3)
        _check("version.ai_analysis", "数据洞察" in (sofa["version"]["ai_analysis"] or ""))
        _check("error 竞品被记录", fotmob["version"]["error"] == "store fetch failed")

        print("\n=== 4. Comments 数据 ===")
        _check("comments.total 跨地区累加", sofa["comments"]["total"] == 30 + 12)
        _check("comments.negative 跨地区累加", sofa["comments"]["negative"] == 18 + 6)
        _check("labels 跨地区合并", sofa["comments"]["labels"]["[问题抱怨]"] == 14)
        _check("by_region 含地区 label", sofa["comments"]["by_region"]["us"]["label"] == "美国")
        _check("weekly_summary 透传", "美国市场" in (sofa["comments"]["weekly_summary"] or ""))
        _check("deep_analysis 来自 competitor_detail", "Widgets" in (sofa["comments"]["deep_analysis"] or ""))
        _check("feature_keywords 来自 detail", sofa["comments"]["feature_keywords"]["widget"] == 10)

        print("\n=== 5. Commercial 数据 ===")
        _check("price_alerts 透传", len(sofa["commercial"]["price_alerts"]) == 1)
        _check("iap_changes 透传", sofa["commercial"]["iap_changes"][0]["type"] == "新增")
        _check("betting_signals 标记", one["commercial"]["betting_signals"] is True)
        _check("rpd_index 透传", abs(sofa["commercial"]["rpd_index"] - 1.42) < 0.001)

        print("\n=== 6. Alerts 预警规则 ===")
        alerts = payload["alerts"]
        types = [a["type"] for a in alerts]
        _check("触发 negative_review", "negative_review" in types)
        _check("触发 rank_rise", "rank_rise" in types)
        _check("触发 version_update", "version_update" in types)
        _check("触发 commercial_change (price_alert)", any(a["type"] == "commercial_change" and "涨价" in a["title"] for a in alerts))
        _check("触发 commercial_change (betting)", any(a["type"] == "commercial_change" and "博彩" in a["title"] for a in alerts))
        _check("danger 排在 warn 之前", alerts[0]["severity"] == "danger")

        print("\n=== 7. Feed 流 ===")
        feed = payload["feed"]
        _check("feed 含版本变更条目", any(f["type"] == "feature" and f["competitor"] == "SofaScore" for f in feed))
        _check("feed 含评论条目", any(f["type"] == "bug" and f["competitor"] == "SofaScore" for f in feed))

        print("\n=== 8. Views 切片 ===")
        views = payload["views"]
        _check("views.by_region 含 us", "us" in views["by_region"])
        _check("by_region.us.competitors 含 SofaScore", any(c["competitor"] == "SofaScore" for c in views["by_region"]["us"]["competitors"]))
        _check("views.by_label 含 [问题抱怨]", "[问题抱怨]" in views["by_label"])
        _check("by_label 内按 count 倒序", views["by_label"]["[问题抱怨]"][0]["count"] >= views["by_label"]["[问题抱怨]"][-1]["count"])
        _check("timeline 非空", len(views["timeline"]) > 0)
        _check("timeline 含 version_change 事件", any(e["event_type"] == "version_change" for e in views["timeline"]))
        _check("timeline 含 rank_rise 事件", any(e["event_type"] == "rank_rise" for e in views["timeline"]))
        _check("timeline 含 price_alert 事件", any(e["event_type"] == "price_alert" for e in views["timeline"]))

        print("\n=== 9. Metrics 顶部指标 ===")
        m = payload["metrics"]
        _check("metrics.monitored = 6", m["monitored"] == 6)
        _check("metrics.changes_detected 来自 strategy", m["changes_detected"] == 1)
        _check("metrics.max_rank_delta 是 FlashScore 的 +8", m["max_rank_delta"] == 8 and m["max_rank_comp"] == "FlashScore")
        _check("metrics.total_negative 全部累加", m["total_negative"] == 18 + 6 + 0)

        print("\n=== 10. Community Reddit 原始切片 ===")
        community_sofa = sofa["community"]["raw"]
        community_flash = flash["community"]["raw"]
        community_one = one["community"]["raw"]
        _check("SofaScore mention_count = 2 (窗口内 2 条，30 天前 1 条被过滤)", community_sofa["mention_count"] == 2)
        _check("SofaScore total_engagement = (120+45) + (45+10) = 220",
               community_sofa["total_engagement"] == 220, f"got {community_sofa['total_engagement']}")
        _check("subreddit_distribution 含 soccer 和 footballmanagergames",
               set(community_sofa["subreddit_distribution"].keys()) == {"soccer", "footballmanagergames"})
        _check("hot_posts 按 score 倒序",
               community_sofa["hot_posts"][0]["title"] == "SofaScore widget broken")
        _check("recent_comments 仅含窗口内评论",
               len(community_sofa["recent_comments"]) == 2)
        _check("recent_comments 含 FlashScore 对比信号",
               any("FlashScore" in c["body"] for c in community_sofa["recent_comments"]))
        _check("daily_trend 非空",
               len(community_sofa["daily_trend"]) >= 1)
        _check("FlashScore mention_count = 1", community_flash["mention_count"] == 1)
        _check("OneFootball mention_count = 0 (未配数据)", community_one["mention_count"] == 0)
        _check("date_range_days 默认 7", community_sofa["date_range_days"] == 7)

        print("\n=== 11. Community AI 分析合入 ===")
        ai_sofa = sofa["community"]["ai_analysis"]
        ai_flash = flash["community"]["ai_analysis"]
        _check("SofaScore 有 AI 分析", ai_sofa is not None)
        _check("ai.overall_summary 透传", "widgets" in (ai_sofa.get("overall_summary") or ""))
        _check("ai.sentiment 透传", abs(ai_sofa["sentiment"]["negative"] - 0.5) < 0.001)
        _check("ai.top_topics 透传", "widget" in ai_sofa["top_topics"])
        _check("ai.alert_level = medium", ai_sofa["alert_level"] == "medium")
        _check("ai.competitor_mentions 透传", "FlashScore" in ai_sofa["competitor_mentions"])
        _check("FlashScore 没 AI 分析（独立合入逻辑）", ai_flash is None)

        print("\n=== 12. 数据新鲜度 / 配置透传 ===")
        _check("data_freshness.strategy 非空", payload["meta"]["data_freshness"]["strategy"] is not None)
        _check("regions 透传", "us" in payload["regions"])
        _check("competitor_registry 透传", "SofaScore" in payload["competitor_registry"])
        _check("weekly.comment.summary 透传", "美国市场" in (payload["weekly"]["comment"].get("summary") or ""))
        _check("weekly.commercial.summary 透传", "提价" in (payload["weekly"]["commercial"].get("summary") or ""))

        print("\n🎉 全部断言通过")
        return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
