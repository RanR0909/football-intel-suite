#!/usr/bin/env python3
"""数据聚合层。

读取 data/ 下 7 个独立 JSON 数据源 + 2 个配置文件，
输出统一的 data/dashboard_data.json。

用法：
    python3 -m data_pipeline.aggregator
    或
    python3 data_pipeline/aggregator.py

所有原始 JSON 缺失时降级为空容器，dashboard 仍可渲染（显示"暂无数据"）。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 允许独立脚本运行
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_pipeline.schema import (
    AdsInfo,
    Alert,
    CommentInfo,
    CommercialInfo,
    CommunityAI,
    CommunityInfo,
    CommunityRaw,
    CompetitorSnapshot,
    DashboardData,
    DataFreshness,
    FeedItem,
    Meta,
    Metrics,
    ProductUpdateItem,
    ProductUpdatesView,
    RankInfo,
    ReviewAnalysisView,
    ReviewItem,
    TimelineEvent,
    VersionInfo,
    Views,
    WeeklyData,
    to_dict,
)


# ---------------------------------------------------------------------------
# 路径 / 常量
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUTPUT_PATH = DATA_DIR / "dashboard_data.json"

DEFAULT_COMMUNITY_DAYS = 7
COMMUNITY_HOT_POST_LIMIT = 10
COMMUNITY_RECENT_COMMENT_LIMIT = 20

COMP_COLORS = {
    "SofaScore": "#7b6ef6",
    "FlashScore": "#4ecca3",
    "OneFootball": "#f5a623",
    "365Scores": "#ff5c5c",
    "Fotmob": "#60a5fa",
    "LiveScore": "#a78bfa",
    "ESPN": "#f472b6",
    "theScore": "#34d399",
}
COLOR_FALLBACK = ["#7b6ef6", "#4ecca3", "#f5a623", "#ff5c5c", "#60a5fa", "#a78bfa", "#f472b6", "#34d399"]

VERSION_FEATURE_KEYWORDS = [
    "功能", "feature", "new", "更新", "上线", "新增",
    "redesign", "redesigned", "widget", "widgets",
    "multiview", "lineup", "depth chart", "insight",
    "AI", "ai", "智能", "分析", "统计", "stat", "数据",
]


# ---------------------------------------------------------------------------
# 文件加载
# ---------------------------------------------------------------------------

def _load_json(filename: str) -> dict:
    fp = DATA_DIR / filename
    if not fp.exists():
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_competitor_details() -> dict:
    """加载所有 competitor_detail_*.json，返回 {name: data}。"""
    out = {}
    for fp in DATA_DIR.glob("competitor_detail_*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            name = data.get("competitor", "")
            if name:
                out[name] = data
        except Exception:
            continue
    return out


def _load_reddit_raw() -> list:
    """读 data/raw/reddit_posts.json — RedditCrawler 的产物。

    期望格式：list of {timestamp, source, competitor, data: {posts: [...]}}。
    """
    fp = RAW_DIR / "reddit_posts.json"
    if not fp.exists():
        return []
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _load_community_ai() -> dict:
    """读 data/community_ai_analysis.json — AI 分析独立持久化文件。

    格式：{<competitor_name>: {overall_summary, sentiment, ...}}
    """
    return _load_json("community_ai_analysis.json") or {}


def _load_fb_adlib_raw() -> list:
    """读 BaseCrawler 默认产物 data/async_fb_adlib.json。

    每条 record: {timestamp, source, competitor, region, data: {ad_count, ads: [...]}}
    同一竞品按国家分多条 record。
    """
    data = _load_json("async_fb_adlib.json")
    return data if isinstance(data, list) else []


def _load_ads_ai() -> dict:
    """Phase 3 预留：data/ads_ai_analysis.json。"""
    return _load_json("ads_ai_analysis.json") or {}


# ---------------------------------------------------------------------------
# 竞品快照构建
# ---------------------------------------------------------------------------

def _init_competitors(registry: dict) -> dict[str, CompetitorSnapshot]:
    """以 competitors.json 为主索引，初始化所有 CompetitorSnapshot。"""
    snapshots = {}
    for idx, (name, info) in enumerate(registry.items()):
        snapshots[name] = CompetitorSnapshot(
            id=name,
            name=name,
            color=COMP_COLORS.get(name, COLOR_FALLBACK[idx % len(COLOR_FALLBACK)]),
            ios_id=str(info.get("ios") or info.get("app_id") or "") or None,
            android_id=info.get("gp"),
        )
    return snapshots


def _fill_rank(
    snapshots: dict[str, CompetitorSnapshot],
    market: dict,
    history: dict,
):
    """填充 .rank：current/delta_dod 来自 market_rank；history/delta_wow 来自 ranking_history。"""
    perf = market.get("competitor_performance", {})
    fast_names = {item.get("name") for item in market.get("fast_movers", []) if item.get("name")}
    new_names = {item.get("name") for item in market.get("new_contenders", []) if item.get("name")}

    # 先填 current/delta_dod
    for name, info in perf.items():
        if name not in snapshots:
            # 排名里可能出现未在 competitors.json 注册的应用，跳过（leaderboard 单独保留）
            continue
        snap = snapshots[name]
        snap.rank.current = info.get("rank")
        snap.rank.delta_dod = info.get("delta")
        snap.rank.app_id = info.get("app_id") or snap.ios_id
        snap.rank.fast_mover = name in fast_names
        snap.rank.is_new_contender = name in new_names

    # 构建 app_id → name 反查
    id_to_name = {}
    for name, snap in snapshots.items():
        if snap.rank.app_id:
            id_to_name[str(snap.rank.app_id)] = name
        if snap.ios_id:
            id_to_name[str(snap.ios_id)] = name

    # ranking_history 形如 {date: {app_id: rank}}
    if history:
        dates = sorted(history.keys())
        # 历史轨迹：每个竞品 {date: rank}
        for date in dates:
            day = history[date] or {}
            for app_id, rank in day.items():
                name = id_to_name.get(str(app_id))
                if name and name in snapshots:
                    snapshots[name].rank.history[date] = rank

        # delta_wow：最新日 vs 一周前
        if len(dates) >= 2:
            latest_date = dates[-1]
            try:
                latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
            except ValueError:
                latest_dt = None
            if latest_dt is not None:
                week_ago_str = (latest_dt - timedelta(days=7)).strftime("%Y-%m-%d")
                week_ago_date = None
                for d in dates:
                    if d <= week_ago_str:
                        week_ago_date = d
                    else:
                        break
                if week_ago_date is None:
                    week_ago_date = dates[0]
                if week_ago_date and week_ago_date != latest_date:
                    latest_ranks = history.get(latest_date, {})
                    old_ranks = history.get(week_ago_date, {})
                    for app_id, current_rank in latest_ranks.items():
                        name = id_to_name.get(str(app_id))
                        if not name or name not in snapshots:
                            continue
                        if app_id in old_ranks:
                            old_rank = old_ranks[app_id]
                            # 正数 = 排名上升（数字变小）
                            snapshots[name].rank.delta_wow = old_rank - current_rank


def _fill_version(snapshots: dict[str, CompetitorSnapshot], strategy: dict):
    for name, info in strategy.get("competitors", {}).items():
        if name not in snapshots:
            continue
        snap = snapshots[name]
        if "error" in info:
            snap.version.error = info["error"]
            continue
        snap.version.current = info.get("version")
        snap.version.release_notes = info.get("release_notes")
        snap.version.release_date = info.get("release_date")     # Phase C：strategy_monitor 抓到时填充
        snap.version.has_changed = bool(info.get("has_changed"))
        snap.version.version_changed = bool(info.get("version_changed"))
        snap.version.is_first_record = bool(info.get("is_first_record"))
        snap.version.changes = list(info.get("changes") or [])
        snap.version.in_app_purchases = list(info.get("in_app_purchases") or [])
        snap.version.ai_analysis = info.get("analysis")


def _fill_comments(
    snapshots: dict[str, CompetitorSnapshot],
    comments: dict,
    weekly: dict,
    details: dict,
    regions_cfg: dict,
):
    for name, info in comments.get("competitors", {}).items():
        if name not in snapshots:
            continue
        snap = snapshots[name]
        total = 0
        negative = 0
        merged_labels: Counter = Counter()
        by_region = {}

        for region_code, region_data in (info.get("regions") or {}).items():
            count = int(region_data.get("count", 0) or 0)
            neg = int(region_data.get("negative_count", count) or 0)
            labels = dict(region_data.get("labels") or {})
            total += count
            negative += neg
            for label, c in labels.items():
                if c:
                    merged_labels[label] += int(c)

            by_region[region_code] = {
                "label": (regions_cfg.get(region_code) or {}).get("label", region_code),
                "lang": (regions_cfg.get(region_code) or {}).get("lang"),
                "count": count,
                "negative_count": neg,
                "labels": labels,
                "summary": region_data.get("summary", ""),
                "reviews": list(region_data.get("reviews") or []),
            }

        snap.comments.total = total
        snap.comments.negative = negative
        snap.comments.labels = dict(merged_labels)
        snap.comments.by_region = by_region

    # weekly_review.per_competitor[name] -> snap.comments.weekly_summary (取全局 summary 也可，per_competitor 没字符串就用 total)
    weekly_summary = weekly.get("summary") if weekly else None
    if weekly_summary:
        # 全局 summary 是统一文本；per_competitor 只有数据没 AI 文案
        # 先全部挂上同一个全局摘要，竞品详情页可识别"该周报覆盖到此竞品"
        for name in snapshots:
            if name in (weekly.get("per_competitor") or {}):
                snapshots[name].comments.weekly_summary = weekly_summary

    # competitor_detail_*.json
    for name, detail in details.items():
        if name not in snapshots:
            continue
        snap = snapshots[name]
        fa = detail.get("feature_analysis") or {}
        if fa.get("summary"):
            snap.comments.deep_analysis = fa["summary"]
        if fa.get("feature_keywords"):
            snap.comments.feature_keywords = dict(fa["feature_keywords"])


SENTIMENT_BY_LABEL = {
    "[问题抱怨]":         "negative",
    "[流失信号]":         "negative",
    "[竞品对比]":         "negative",      # 用户提对手通常隐含"X 比你强"，商业上是威胁
    "[高价值功能请求]":    "neutral",       # 想要更多 = 仍在用，机会信号但不算负面
    "[正向反馈]":         "positive",
    "[其他]":             "neutral",
}


def _derive_sentiment(label: str | None, rating: int) -> str:
    """从 label 派生情绪；无 label 时按 rating 兜底。"""
    if label and label in SENTIMENT_BY_LABEL:
        return SENTIMENT_BY_LABEL[label]
    if rating >= 4:
        return "positive"
    if rating and rating <= 2:
        return "negative"
    return "neutral"


def _build_review_analysis(
    snapshots: dict[str, CompetitorSnapshot],
    regions_cfg: dict,
) -> ReviewAnalysisView:
    """从 snapshot.comments.by_region.reviews 派生扁平视图 + 聚合 metrics。"""
    items: list[ReviewItem] = []
    overall_sentiment: Counter = Counter()
    overall_topic: Counter = Counter()
    pos_topic: Counter = Counter()
    neg_topic: Counter = Counter()
    by_comp: dict = {}

    for name, snap in snapshots.items():
        comp_sentiment: Counter = Counter()
        comp_topic: Counter = Counter()
        comp_total = 0

        for region_code, r in (snap.comments.by_region or {}).items():
            region_label = (regions_cfg.get(region_code) or {}).get("label", region_code)
            ios_id = snap.ios_id
            source_url = (
                f"https://apps.apple.com/{region_code}/app/id{ios_id}?see-all=reviews"
                if ios_id else None
            )

            for rv in r.get("reviews") or []:
                label = rv.get("label", "") or ""
                rating = int(rv.get("score") or rv.get("rating") or 0)
                sentiment = _derive_sentiment(label, rating)
                platform = rv.get("platform") or "App Store"

                items.append(ReviewItem(
                    competitor=name,
                    region=region_code,
                    region_label=region_label,
                    platform=platform,
                    rating=rating,
                    version=rv.get("version", "") or "",
                    content=rv.get("content", "") or "",
                    label=label,
                    sentiment=sentiment,
                    source_url=source_url,
                ))

                overall_sentiment[sentiment] += 1
                comp_sentiment[sentiment] += 1
                if label:
                    overall_topic[label] += 1
                    comp_topic[label] += 1
                    if sentiment == "positive":
                        pos_topic[label] += 1
                    elif sentiment == "negative":
                        neg_topic[label] += 1
                comp_total += 1

        if comp_total > 0:
            by_comp[name] = {
                "total": comp_total,
                "sentiment_count": dict(comp_sentiment),
                "topic_count": dict(comp_topic),
            }

    return ReviewAnalysisView(
        metrics={
            "total": sum(overall_sentiment.values()),
            "sentiment_count": dict(overall_sentiment),
            "topic_count": dict(overall_topic),
            "by_competitor": by_comp,
            "top_negative_topics": [{"topic": t, "count": c} for t, c in neg_topic.most_common(3)],
            "top_positive_topics": [{"topic": t, "count": c} for t, c in pos_topic.most_common(3)],
        },
        items=items,
    )


def _build_product_updates(
    snapshots: dict[str, CompetitorSnapshot],
    days: int = 7,
) -> ProductUpdatesView:
    """从 snapshots[*].version 派生 product_updates 视图（metrics + items）。

    分类逻辑使用 strategy_monitor.changelog_classifier，不修改 snap.version 本身（保持单一真实数据源）。
    时间窗用 release_date 优先，缺失时用 has_changed / is_first_record 兜底（保证 strategy_monitor 未抓 date 也能渲染）。
    """
    from strategy_monitor.changelog_classifier import classify_changelog

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    items: list[ProductUpdateItem] = []
    metrics = {
        "week_total": 0, "week_feature": 0,
        "week_bugfix": 0, "week_pricing": 0,
        "week_localization": 0,
    }

    for name, snap in snapshots.items():
        v = snap.version
        if v.error:
            continue
        # 仅当 strategy_monitor 中存在该竞品的真实数据时才进 items
        if not (v.current or v.release_notes or v.has_changed or v.is_first_record or v.changes):
            continue
        change_type, tags = classify_changelog(v.release_notes, v.changes)
        v.change_type = change_type
        v.change_tags = tags

        # 摘要：优先 changes 列表（精炼），否则 release_notes 截断
        if v.changes:
            summary = "；".join(v.changes[:3])
        elif v.release_notes:
            summary = v.release_notes.strip()[:200]
        else:
            summary = "（无更新日志）"

        # source_url：用 ios_id 拼 App Store 应用页（含 changelog）
        ios_id = snap.ios_id
        gp_id = snap.android_id
        source_url = None
        if ios_id:
            source_url = f"https://apps.apple.com/us/app/id{ios_id}"
        elif gp_id:
            source_url = f"https://play.google.com/store/apps/details?id={gp_id}"

        # release_date 可能含 'T' 时间分；统一截 10 位
        date_str = (v.release_date or "")[:10] or None

        items.append(ProductUpdateItem(
            competitor=name,
            version=v.current,
            date=date_str,
            type=change_type,
            tags=list(tags),
            summary=summary,
            source_url=source_url,
            has_changed=bool(v.has_changed),
            is_first_record=bool(v.is_first_record),
        ))

        # 周聚合：仅统计真发生变化的；date 缺失时用 has_changed/is_first_record 兜底
        in_window = (
            (date_str and date_str >= cutoff) or
            (not date_str and (v.has_changed or v.is_first_record))
        )
        if in_window:
            metrics["week_total"] += 1
            metrics["week_" + change_type] += 1

    # date desc 排序，缺失日期排后面
    items.sort(key=lambda x: x.date or "", reverse=True)

    return ProductUpdatesView(metrics=metrics, items=items)


def _fill_community(
    snapshots: dict[str, CompetitorSnapshot],
    reddit_raw: list,
    ai_results: dict,
    days: int = DEFAULT_COMMUNITY_DAYS,
):
    """合并 Reddit 原始数据 + AI 分析结果到每个竞品的 community 字段。

    时间窗按 created_utc 过滤（默认 7 天）。所有计数 / 趋势 / 热门帖均基于窗口内数据。
    AI 分析独立透传，数据缺失时保持 None。
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()

    posts_by_comp: dict[str, list] = {}
    for rec in reddit_raw:
        comp = rec.get("competitor")
        if not comp:
            continue
        for p in (rec.get("data", {}) or {}).get("posts") or []:
            posts_by_comp.setdefault(comp, []).append(p)

    for name, snap in snapshots.items():
        all_posts = posts_by_comp.get(name, [])
        posts = [p for p in all_posts if (p.get("created_utc") or 0) >= cutoff]

        sub_dist: Counter = Counter()
        daily: dict[str, list] = {}
        all_comments: list = []
        engagement = 0

        for p in posts:
            sub_dist[p.get("subreddit") or "unknown"] += 1
            engagement += int(p.get("score") or 0) + int(p.get("num_comments") or 0)

            d = datetime.fromtimestamp(p.get("created_utc") or 0, tz=timezone.utc).strftime("%Y-%m-%d")
            entry = daily.setdefault(d, [0, 0])
            entry[0] += 1

            for c in p.get("comments") or []:
                ts = c.get("created_utc") or 0
                if ts < cutoff:
                    continue
                all_comments.append({
                    "post_title": p.get("title", ""),
                    "subreddit": p.get("subreddit"),
                    "body": c.get("body", ""),
                    "score": c.get("score", 0),
                    "created_utc": ts,
                })
                cd = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                centry = daily.setdefault(cd, [0, 0])
                centry[1] += 1

        hot = sorted(posts, key=lambda x: x.get("score", 0), reverse=True)[:COMMUNITY_HOT_POST_LIMIT]
        recent = sorted(all_comments, key=lambda x: x.get("created_utc", 0), reverse=True)[:COMMUNITY_RECENT_COMMENT_LIMIT]

        snap.community.raw = CommunityRaw(
            mention_count=len(posts),
            total_engagement=engagement,
            hot_posts=[{
                "title": p.get("title", ""),
                "subreddit": p.get("subreddit"),
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "url": p.get("url"),
                "created_at": datetime.fromtimestamp(p.get("created_utc") or 0, tz=timezone.utc).isoformat(),
            } for p in hot],
            recent_comments=recent,
            subreddit_distribution=dict(sub_dist),
            daily_trend=[{"date": d, "posts": v[0], "comments": v[1]} for d, v in sorted(daily.items())],
            date_range_days=days,
        )

        if name in ai_results:
            ai = ai_results[name] or {}
            snap.community.ai_analysis = CommunityAI(
                overall_summary=ai.get("overall_summary"),
                sentiment=dict(ai.get("sentiment") or {}),
                top_topics=list(ai.get("top_topics") or []),
                pain_points=list(ai.get("pain_points") or []),
                opportunities=list(ai.get("opportunities") or []),
                competitor_mentions=list(ai.get("competitor_mentions") or []),
                representative_quotes=list(ai.get("representative_quotes") or []),
                alert_level=ai.get("alert_level", "low") or "low",
                generated_at=ai.get("generated_at"),
                date_range_days=ai.get("date_range_days"),
                sample_size=ai.get("sample_size"),
            )


def _fill_ads(
    snapshots: dict[str, CompetitorSnapshot],
    fb_raw: list,
    ads_ai: dict,
):
    """把 fb_adlib 数据按竞品聚合 → AdsInfo → 挂到 snap.commercial.ads。

    在 _fill_commercial 之后调用，仅覆写 commercial.ads，不影响其他商业字段。
    """
    from commercial_strategy.ads_processor import process_competitor_ads

    by_comp: dict[str, list] = {}
    for rec in fb_raw:
        comp = rec.get("competitor")
        if comp:
            by_comp.setdefault(comp, []).append(rec)

    for name, snap in snapshots.items():
        records = by_comp.get(name, [])
        info_dict = process_competitor_ads(records) if records else {}
        if not info_dict:
            continue
        # Phase 3 预留：合入独立持久化的 AI 分析
        ai = ads_ai.get(name)
        if ai:
            info_dict["ai_analysis"] = ai     # Phase 1 schema 不含此字段，扩展时再加
        snap.commercial.ads = AdsInfo(
            **{k: v for k, v in info_dict.items() if k in AdsInfo.__dataclass_fields__}
        )


def _fill_commercial(snapshots: dict[str, CompetitorSnapshot], commercial: dict):
    for name, info in commercial.get("competitors", {}).items():
        if name not in snapshots:
            continue
        snap = snapshots[name]
        snap.commercial = CommercialInfo(
            monetization_tags=list(info.get("monetization_tags") or []),
            iap_items=list(info.get("iap_items") or []),
            price_alerts=list(info.get("price_alerts") or []),
            iap_changes=list(info.get("iap_changes") or []),
            rpd_index=info.get("rpd_index"),
            rank=info.get("rank"),
            betting_signals=bool(info.get("betting_signals")),
            description_keywords=list(info.get("description_keywords") or []),
            seller_url=info.get("seller_url"),
            ai_intent=info.get("ai_intent"),
        )


# ---------------------------------------------------------------------------
# 预警 / Feed / 指标
# ---------------------------------------------------------------------------

def _build_alerts(snapshots: dict[str, CompetitorSnapshot]) -> list[Alert]:
    """规则迁移自 generate_dashboard.build_alerts，逻辑保持一致。"""
    alerts: list[Alert] = []

    # 规则 1：低星评论
    for name, snap in snapshots.items():
        if snap.comments.negative <= 0:
            continue
        label_counter = Counter(snap.comments.labels)
        top = "、".join(f"{lab}({c}条)" for lab, c in label_counter.most_common(3))
        alerts.append(Alert(
            type="negative_review",
            severity="danger",
            severity_label="高威胁",
            icon="",
            title=f"{name} 出现低星评论",
            desc=f"近 3 天检测到 {snap.comments.negative} 条低星评论，共抓取 {snap.comments.total} 条评论。高频信号：{top or '暂无标签分布'}。",
            time="今天",
            competitor=name,
        ))

    # 规则 2：一周内排名上升 > 10 位
    for name, snap in snapshots.items():
        delta = snap.rank.delta_wow
        if delta is not None and delta > 10:
            old = (snap.rank.current or 0) + delta
            alerts.append(Alert(
                type="rank_rise",
                severity="warn",
                severity_label="中威胁",
                icon="",
                title=f"{name} 排名快速上升 {delta} 位",
                desc=f"一周内从 #{old} 上升至 #{snap.rank.current}，上升 {delta} 位，买量或功能更新信号明显。",
                time="本周",
                competitor=name,
                payload={"old_rank": old, "new_rank": snap.rank.current, "delta": delta},
            ))

    # 规则 3：版本迭代涉及功能内容
    for name, snap in snapshots.items():
        v = snap.version
        if not (v.has_changed or v.version_changed):
            continue
        has_feature = bool(v.changes)
        if not has_feature and v.release_notes:
            notes_lower = v.release_notes.lower()
            has_feature = any(kw.lower() in notes_lower for kw in VERSION_FEATURE_KEYWORDS)
        if not has_feature:
            continue
        if v.changes:
            change_summary = "；".join(v.changes[:3])
        elif v.release_notes:
            change_summary = v.release_notes[:100].replace("\n", " ").strip() + "..."
        else:
            change_summary = f"版本 {v.current} 有更新内容，建议立即评估差异化策略。"
        alerts.append(Alert(
            type="version_update",
            severity="danger",
            severity_label="高威胁 · 建议评估",
            icon="",
            title=f"{name} 版本更新至 v{v.current or '未知'}，涉及功能变更",
            desc=change_summary,
            time="今天",
            competitor=name,
            payload={"version": v.current},
        ))

    # 规则 4：商业策略变动
    for name, snap in snapshots.items():
        c = snap.commercial
        for pa in c.price_alerts:
            alerts.append(Alert(
                type="commercial_change",
                severity="danger",
                severity_label="高威胁",
                icon="",
                title=f"{name} IAP {pa.get('direction', '变动')}: {pa.get('name', '')}",
                desc=f"价格从 ${pa.get('prev', 0)} 变为 ${pa.get('curr', 0)}（{pa.get('direction', '')} ${abs(pa.get('delta', 0))}）",
                time="今天",
                competitor=name,
                payload=dict(pa),
            ))
        for ic in c.iap_changes:
            alerts.append(Alert(
                type="commercial_change",
                severity="warn",
                severity_label="中威胁",
                icon="",
                title=f"{name} IAP {ic.get('type', '变动')}: {ic.get('name', '')}",
                desc=f"检测到内购项「{ic.get('name', '')}」{ic.get('type', '变动')}，建议关注竞品商业策略调整。",
                time="今天",
                competitor=name,
                payload=dict(ic),
            ))
        if c.betting_signals:
            alerts.append(Alert(
                type="commercial_change",
                severity="warn",
                severity_label="中威胁",
                icon="",
                title=f"{name} 检测到博彩导流信号",
                desc=f"应用描述中包含博彩相关关键词: {', '.join(c.description_keywords)}",
                time="今天",
                competitor=name,
            ))

    severity_order = {"danger": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda a: severity_order.get(a.severity, 99))
    return alerts


def _build_feed(snapshots: dict[str, CompetitorSnapshot]) -> list[FeedItem]:
    feed: list[FeedItem] = []

    for name, snap in snapshots.items():
        v = snap.version
        if v.error:
            continue
        if v.has_changed:
            for change in v.changes:
                feed.append(FeedItem(
                    competitor=name,
                    type="feature",
                    text=change,
                    time="今天",
                    version=v.current or "",
                ))
        elif v.is_first_record:
            feed.append(FeedItem(
                competitor=name,
                type="update",
                text=f"首次记录 · 版本 {v.current or '未知'}",
                time="今天",
                version=v.current or "",
            ))

    for name, snap in snapshots.items():
        if snap.comments.total > 0:
            feed.append(FeedItem(
                competitor=name,
                type="bug",
                text=f"新增 {snap.comments.total} 条用户评论，其中 {snap.comments.negative} 条为低星评论",
                time="今天",
                payload={"total": snap.comments.total, "negative": snap.comments.negative},
            ))

    return feed


def _build_metrics(snapshots: dict[str, CompetitorSnapshot], strategy: dict) -> Metrics:
    monitored = strategy.get("total_monitored", 0) if strategy else len(snapshots)
    changes_detected = strategy.get("changes_detected", 0) if strategy else 0

    max_delta = 0
    max_comp = ""
    for name, snap in snapshots.items():
        d = snap.rank.delta_dod
        if d is not None and abs(d) > abs(max_delta):
            max_delta = d
            max_comp = name

    total_negative = sum(s.comments.negative for s in snapshots.values())

    return Metrics(
        changes_detected=changes_detected,
        max_rank_delta=max_delta,
        max_rank_comp=max_comp,
        total_negative=total_negative,
        monitored=monitored,
    )


# ---------------------------------------------------------------------------
# 切片视图
# ---------------------------------------------------------------------------

def _build_views(snapshots: dict[str, CompetitorSnapshot], regions_cfg: dict) -> Views:
    by_region: dict = {}
    by_label: dict = {}
    timeline: list = []

    # by_region：每地区 → 该地区所有竞品的 count/negative/labels
    for region_code, region_meta in regions_cfg.items():
        entries = []
        for name, snap in snapshots.items():
            r = snap.comments.by_region.get(region_code)
            if not r:
                continue
            entries.append({
                "competitor": name,
                "color": snap.color,
                "count": r["count"],
                "negative_count": r["negative_count"],
                "labels": r["labels"],
            })
        if entries:
            by_region[region_code] = {
                "label": region_meta.get("label", region_code),
                "lang": region_meta.get("lang"),
                "competitors": entries,
            }

    # by_label：标签 → [{competitor, region, count}]
    for name, snap in snapshots.items():
        for region_code, r in snap.comments.by_region.items():
            for label, count in (r.get("labels") or {}).items():
                if not count:
                    continue
                by_label.setdefault(label, []).append({
                    "competitor": name,
                    "region": region_code,
                    "region_label": r.get("label", region_code),
                    "count": int(count),
                })
    for label in by_label:
        by_label[label].sort(key=lambda x: -x["count"])

    # timeline：合并各类事件
    now_iso = datetime.now().isoformat()
    for name, snap in snapshots.items():
        v = snap.version
        if v.has_changed and v.changes:
            timeline.append(TimelineEvent(
                ts=now_iso, competitor=name, event_type="version_change",
                title=f"{name} v{v.current or '?'} 功能更新",
                payload={"version": v.current, "changes": v.changes},
            ))
        if snap.rank.delta_wow is not None and snap.rank.delta_wow > 10:
            timeline.append(TimelineEvent(
                ts=now_iso, competitor=name, event_type="rank_rise",
                title=f"{name} 排名上升 {snap.rank.delta_wow} 位",
                payload={"delta": snap.rank.delta_wow, "current": snap.rank.current},
            ))
        for pa in snap.commercial.price_alerts:
            timeline.append(TimelineEvent(
                ts=now_iso, competitor=name, event_type="price_alert",
                title=f"{name} IAP {pa.get('direction', '变动')}: {pa.get('name', '')}",
                payload=dict(pa),
            ))
        for ic in snap.commercial.iap_changes:
            timeline.append(TimelineEvent(
                ts=now_iso, competitor=name, event_type="iap_change",
                title=f"{name} IAP {ic.get('type', '变动')}: {ic.get('name', '')}",
                payload=dict(ic),
            ))
        if snap.comments.negative > 0:
            timeline.append(TimelineEvent(
                ts=now_iso, competitor=name, event_type="negative_review",
                title=f"{name} 出现 {snap.comments.negative} 条低星评论",
                payload={"negative": snap.comments.negative, "total": snap.comments.total},
            ))

    timeline.sort(key=lambda e: e.ts, reverse=True)
    return Views(by_region=by_region, by_label=by_label, timeline=[to_dict(e) for e in timeline])


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def build_dashboard_data() -> DashboardData:
    registry = _load_json("competitors.json")
    regions_cfg = _load_json("regions.json")
    strategy = _load_json("strategy_monitor.json")
    market = _load_json("market_rank.json")
    history = _load_json("ranking_history.json")
    comments = _load_json("competitor_comments.json")
    weekly = _load_json("weekly_review.json")
    commercial = _load_json("commercial_strategy.json")
    commercial_weekly = _load_json("commercial_weekly.json")
    details = _load_competitor_details()

    reddit_raw = _load_reddit_raw()
    community_ai = _load_community_ai()
    fb_raw = _load_fb_adlib_raw()
    ads_ai = _load_ads_ai()

    snapshots = _init_competitors(registry)
    _fill_rank(snapshots, market, history)
    _fill_version(snapshots, strategy)
    _fill_comments(snapshots, comments, weekly, details, regions_cfg)
    _fill_commercial(snapshots, commercial)
    _fill_ads(snapshots, fb_raw, ads_ai)
    _fill_community(snapshots, reddit_raw, community_ai)
    product_updates = _build_product_updates(snapshots)
    reviews_analysis = _build_review_analysis(snapshots, regions_cfg)

    alerts = _build_alerts(snapshots)
    feed = _build_feed(snapshots)
    metrics = _build_metrics(snapshots, strategy)
    views = _build_views(snapshots, regions_cfg)

    freshness = DataFreshness(
        comments=comments.get("generated_at"),
        rank=market.get("generated_at"),
        strategy=strategy.get("generated_at"),
        commercial=commercial.get("generated_at"),
        weekly_review=weekly.get("generated_at"),
        commercial_weekly=commercial_weekly.get("generated_at"),
    )

    return DashboardData(
        meta=Meta(generated_at=datetime.now().isoformat(), data_freshness=freshness),
        competitors={name: snap for name, snap in snapshots.items()},
        views=views,
        alerts=alerts,
        feed=feed,
        leaderboard=list(market.get("leaderboard") or []),
        new_contenders=list(market.get("new_contenders") or []),
        fast_movers=list(market.get("fast_movers") or []),
        weekly=WeeklyData(comment=weekly or {}, commercial=commercial_weekly or {}),
        metrics=metrics,
        regions=regions_cfg,
        competitor_registry=registry,
        multi_source=dict(market.get("multi_source") or {}),
        baseline={
            "app": market.get("baseline_app"),
            "label": market.get("baseline_label"),
            "comparison": market.get("baseline_comparison") or {},
        },
        ai_brief=market.get("ai_brief"),
        product_updates=product_updates,
        reviews_analysis=reviews_analysis,
    )


def _diagnose_review_coverage(payload: dict) -> None:
    """若注册竞品有 N 个但 reviews_analysis 只覆盖了部分，stderr 警告。

    专门排查"用户评论分析模块只显示 SofaScore"这类数据缺失问题。
    """
    registered = set((payload.get("competitor_registry") or {}).keys())
    if not registered:
        return
    reviewed = set(((payload.get("reviews_analysis") or {}).get("metrics") or {}).get("by_competitor", {}).keys())
    missing = registered - reviewed
    if reviewed and missing:
        print(
            f"[warn] reviews_analysis 仅覆盖 {sorted(reviewed)} ({len(reviewed)}/{len(registered)}). "
            f"缺失：{sorted(missing)} — 检查 competitor_comment/auto_report.py 是否对全部竞品执行成功",
            file=sys.stderr,
        )


def main() -> int:
    data = build_dashboard_data()
    payload = to_dict(data)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[aggregator] wrote {OUTPUT_PATH}")
    print(f"[aggregator] competitors: {len(payload['competitors'])}")
    print(f"[aggregator] alerts: {len(payload['alerts'])}, feed: {len(payload['feed'])}, timeline: {len(payload['views']['timeline'])}")
    _diagnose_review_coverage(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
