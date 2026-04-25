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
from datetime import datetime, timedelta
from pathlib import Path

# 允许独立脚本运行
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_pipeline.schema import (
    Alert,
    CommentInfo,
    CommercialInfo,
    CompetitorSnapshot,
    DashboardData,
    DataFreshness,
    FeedItem,
    Meta,
    Metrics,
    RankInfo,
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
OUTPUT_PATH = DATA_DIR / "dashboard_data.json"

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
            icon="🔴",
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
                icon="📈",
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
            icon="⚡",
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
                icon="💰",
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
                icon="💰",
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
                icon="🎰",
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

    snapshots = _init_competitors(registry)
    _fill_rank(snapshots, market, history)
    _fill_version(snapshots, strategy)
    _fill_comments(snapshots, comments, weekly, details, regions_cfg)
    _fill_commercial(snapshots, commercial)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
