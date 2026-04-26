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
    today = datetime.now()

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
                "release_notes": "minor bug fixes and crash fixes",
                "release_date": today.strftime("%Y-%m-%d"),
                "has_changed": True,
                "is_first_record": False,
                "version_changed": True,
                "iap_changed": False,
                "changes": [],
            },
            "OneFootball": {
                "version": "16.5",
                "release_notes": "Premium subscription pricing updated, free trial 7 days",
                "release_date": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
                "has_changed": True,
                "is_first_record": False,
                "version_changed": True,
                "iap_changed": True,
                "changes": [],
            },
            "365Scores": {
                "version": "12.3",
                "release_notes": "Now available in Portuguese and Spanish languages",
                "release_date": (today - timedelta(days=5)).strftime("%Y-%m-%d"),
                "has_changed": True,
                "is_first_record": False,
                "version_changed": True,
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

    # ---- data/async_fb_adlib.json：构造 SofaScore 多区域、新旧广告混合 ----
    fb_now_iso = today.isoformat()
    in_window_new = (today - timedelta(days=1)).strftime("%Y-%m-%d")    # 1 天前 → new_ads
    in_window_recent = (today - timedelta(days=4)).strftime("%Y-%m-%d") # 4 天前 → recent_bucket
    prior_window = (today - timedelta(days=10)).strftime("%Y-%m-%d")    # 10 天前 → prior_bucket
    out_of_window = (today - timedelta(days=30)).strftime("%Y-%m-%d")   # 30 天前 → 仅计入 active_count，不计入 trend
    _write(data_dir / "async_fb_adlib.json", [
        # SofaScore × US：4 条广告，3 类时间窗
        {
            "timestamp": fb_now_iso, "source": "fb_adlib",
            "competitor": "SofaScore", "region": "us",
            "data": {
                "ad_count": 4,
                "ads": [
                    {"ad_id": "a1", "text": "Live scores live now", "start_date": in_window_new, "country": "US"},
                    {"ad_id": "a2", "text": "VIP unlock advanced stats", "start_date": in_window_recent, "country": "US"},
                    {"ad_id": "a3", "text": "Real-time updates", "start_date": in_window_recent, "country": "US"},
                    {"ad_id": "a4_old", "text": "old ad", "start_date": out_of_window, "country": "US"},
                ],
            },
        },
        # SofaScore × GB：1 条
        {
            "timestamp": fb_now_iso, "source": "fb_adlib",
            "competitor": "SofaScore", "region": "gb",
            "data": {
                "ad_count": 2,
                "ads": [
                    {"ad_id": "a5", "text": "EPL live coverage", "start_date": prior_window, "country": "GB"},
                    {"ad_id": "a1", "text": "duplicate id should dedup", "start_date": in_window_new, "country": "GB"},
                ],
            },
        },
        # FlashScore × BR：仅 1 条（trend prior=0, recent=1 → increasing）
        {
            "timestamp": fb_now_iso, "source": "fb_adlib",
            "competitor": "FlashScore", "region": "br",
            "data": {
                "ad_count": 1,
                "ads": [
                    {"ad_id": "f1", "text": "Apostas e palpites", "start_date": in_window_new, "country": "BR"},
                ],
            },
        },
    ])

    # ---- data/ads_ai_analysis.json：仅 SofaScore 已生成 AI（Phase 3） ----
    _write(data_dir / "ads_ai_analysis.json", {
        "SofaScore": {
            "core_strategy": "SofaScore 当前正在通过 VIP 订阅 + 实时比分双卖点扩张 US 市场。",
            "target_persona": ["欧美硬核球迷", "数据驱动用户"],
            "value_props": ["实时比分", "VIP 数据深度", "无广告体验"],
            "geo_focus": ["US", "GB"],
            "opportunities": ["对标 VIP 转化漏斗", "补足赛事数据深度"],
            "risks": ["竞品 VIP 转化能力或将在 30 天内达到拐点，建议同步推 VIP 试用素材"],
            "alert_level": "medium",
            "confidence": "high",
            "generated_at": today.isoformat(),
            "sample_size": 5,
        },
    })

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
    today = datetime.now()
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

        print("\n=== 12. Commercial Ads（Phase 1：投放规模/趋势） ===")
        ads_sofa = sofa["commercial"]["ads"]
        ads_flash = flash["commercial"]["ads"]
        ads_one = one["commercial"]["ads"]
        # SofaScore: 5 条广告（a1 跨 US+GB 去重 → a1, a2, a3, a4_old, a5 = 5），但 fixture 提供的实际去重应该是 5
        _check("SofaScore active_count = 5（跨 region 按 ad_id 去重）", ads_sofa["active_count"] == 5,
               f"got {ads_sofa['active_count']}")
        _check("SofaScore new_ads = 1（仅 a1 在 3 天内）", ads_sofa["new_ads"] == 1)
        _check("SofaScore by_country US:4 GB:1（a1 跨 region 已按首次出现归 US）",
               ads_sofa["by_country"].get("US") == 4 and ads_sofa["by_country"].get("GB") == 1,
               f"got {ads_sofa['by_country']}")
        _check("SofaScore daily_trend 含 4 个日期", len(ads_sofa["daily_trend"]) == 4)
        _check("SofaScore trend 指向 increasing（recent 3 vs prior 1）",
               ads_sofa["trend"] == "increasing", f"got {ads_sofa['trend']}")
        _check("SofaScore last_updated 透传",
               ads_sofa.get("last_updated") is not None)
        _check("FlashScore active_count = 1", ads_flash["active_count"] == 1)
        _check("FlashScore trend = increasing（prior=0, recent>=1）", ads_flash["trend"] == "increasing")
        _check("FlashScore by_country BR:1", ads_flash["by_country"].get("BR") == 1)
        _check("OneFootball active_count = 0（无 fb_adlib 数据）", ads_one["active_count"] == 0)
        _check("OneFootball ads 字段是默认值", ads_one["trend"] == "stable")

        print("\n=== 13. Commercial Ads（Phase 2：themes/segments/patterns/creatives） ===")
        # 文案命中（基于 ads_keywords.py）：
        #   a1 "Live scores live now"           → 实时比分
        #   a2 "VIP unlock advanced stats"      → VIP / 订阅 + 赛事数据（"stats"）+ 硬核球迷
        #   a3 "Real-time updates"              → 实时比分
        #   a4_old "old ad"                     → 无命中
        #   a5 "EPL live coverage"              → 实时比分 + 本地球迷（"epl"）
        themes = {t["theme"]: t["count"] for t in ads_sofa["top_themes"]}
        segments = {s["segment"]: s for s in ads_sofa["user_segments"]}
        _check("top_themes 含'实时比分' 命中 3 次", themes.get("实时比分") == 3, f"got {themes}")
        _check("top_themes 含'VIP / 订阅' 命中 1 次", themes.get("VIP / 订阅") == 1)
        _check("top_themes 按 count 倒序", ads_sofa["top_themes"][0]["theme"] == "实时比分")
        _check("theme.samples 不为空", len(ads_sofa["top_themes"][0]["samples"]) > 0)

        _check("user_segments 含'硬核球迷'", "硬核球迷" in segments)
        _check("user_segments 含'本地球迷'", "本地球迷" in segments)
        _check("signal_strength 默认 low（count=1）", segments["硬核球迷"]["signal_strength"] == "low")

        # creative_diversity：5 条独立文案 / 5 条总文案 = 1.0
        _check("creative_diversity = 1.0（5 条全唯一）", ads_sofa["creative_diversity"] == 1.0)

        creatives = ads_sofa["top_creatives"]
        _check("top_creatives 含 5 条（不含被去重的 a1 重复项）", len(creatives) == 5)
        _check("top_creatives 按 days_running 倒序", creatives[0]["days_running"] >= creatives[-1]["days_running"])
        _check("top_creatives 第一条是最老的 a4_old", creatives[0]["ad_id"] == "a4_old")
        _check("top_creatives 含 themes 标签", isinstance(creatives[0].get("themes"), list))

        # FlashScore（BR · "Apostas e palpites"）→ 博彩导流 + 博彩用户
        flash_themes = {t["theme"] for t in ads_flash["top_themes"]}
        flash_segments = {s["segment"] for s in ads_flash["user_segments"]}
        _check("FlashScore 命中'博彩导流' theme", "博彩导流" in flash_themes, f"got {flash_themes}")
        _check("FlashScore 命中'博彩用户' segment", "博彩用户" in flash_segments)

        # OneFootball 无数据 → Phase 2 字段全部默认空
        _check("OneFootball top_themes 为空", ads_one["top_themes"] == [])
        _check("OneFootball creative_diversity = 0", ads_one["creative_diversity"] == 0.0)

        print("\n=== 14. Commercial Ads（Phase 3：AI 分析合入） ===")
        ai_analysis_sofa = ads_sofa.get("ai_analysis")
        ai_analysis_flash = ads_flash.get("ai_analysis")
        _check("SofaScore ai_analysis 透传", ai_analysis_sofa is not None)
        _check("ai.core_strategy 透传", "VIP" in (ai_analysis_sofa.get("core_strategy") or ""))
        _check("ai.alert_level = medium", ai_analysis_sofa.get("alert_level") == "medium")
        _check("ai.target_persona 透传", "欧美硬核球迷" in (ai_analysis_sofa.get("target_persona") or []))
        _check("FlashScore 没 ai_analysis（独立合入）", ai_analysis_flash is None)

        print("\n=== 15. 产品动态聚合（product_updates） ===")
        pu = payload["product_updates"]
        items_by_comp = {it["competitor"]: it for it in pu["items"]}
        # SofaScore: "redesigned widgets and added AI insight panel" → feature
        _check("SofaScore type=feature", items_by_comp["SofaScore"]["type"] == "feature",
               f"got {items_by_comp['SofaScore']['type']}")
        # FlashScore: "minor bug fixes and crash fixes" → bugfix
        _check("FlashScore type=bugfix", items_by_comp["FlashScore"]["type"] == "bugfix",
               f"got {items_by_comp['FlashScore']['type']}")
        # OneFootball: "Premium subscription pricing updated, free trial" → pricing（优先级最高）
        _check("OneFootball type=pricing（优先级覆盖）", items_by_comp["OneFootball"]["type"] == "pricing",
               f"got {items_by_comp['OneFootball']['type']}")
        # 365Scores: "Portuguese and Spanish languages" → localization
        _check("365Scores type=localization", items_by_comp["365Scores"]["type"] == "localization")

        # release_date 透传
        _check("FlashScore date 等于 today", items_by_comp["FlashScore"]["date"] == today.strftime("%Y-%m-%d"))

        # source_url 拼接
        _check("SofaScore source_url 含 App Store",
               "apps.apple.com" in (items_by_comp["SofaScore"].get("source_url") or ""))

        # error 竞品（Fotmob）不进 items
        _check("Fotmob (error) 不在 items", "Fotmob" not in items_by_comp)
        # LiveScore 没 strategy 数据（默认值），不进 items
        _check("LiveScore (无 strategy) 不在 items", "LiveScore" not in items_by_comp)

        # 时间倒序
        dates = [it["date"] for it in pu["items"] if it["date"]]
        _check("items 按 date 倒序", dates == sorted(dates, reverse=True))

        # 周聚合 metrics
        m = pu["metrics"]
        _check("week_total = 4（4 个有效更新）", m["week_total"] == 4, f"got {m}")
        _check("week_feature = 1（SofaScore）", m["week_feature"] == 1)
        _check("week_bugfix = 1（FlashScore）", m["week_bugfix"] == 1)
        _check("week_pricing = 1（OneFootball）", m["week_pricing"] == 1)
        _check("week_localization = 1（365Scores）", m["week_localization"] == 1)

        # change_tags 多标签：OneFootball 同时命中 pricing + feature（"updated" 不在字典；"trial"/"premium"/"pricing" 在 pricing；"new"... 等不在）
        # 实际只测命中至少 pricing 即可
        _check("OneFootball tags 含 pricing", "pricing" in items_by_comp["OneFootball"]["tags"])

        print("\n=== 16. 数据新鲜度 / 配置透传 ===")
        _check("data_freshness.strategy 非空", payload["meta"]["data_freshness"]["strategy"] is not None)
        _check("regions 透传", "us" in payload["regions"])
        _check("competitor_registry 透传", "SofaScore" in payload["competitor_registry"])
        _check("weekly.comment.summary 透传", "美国市场" in (payload["weekly"]["comment"].get("summary") or ""))
        _check("weekly.commercial.summary 透传", "提价" in (payload["weekly"]["commercial"].get("summary") or ""))

        print("\n🎉 全部断言通过")
        return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
