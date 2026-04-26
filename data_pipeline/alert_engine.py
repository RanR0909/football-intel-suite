"""统一预警引擎。

设计目标：
- 单一入口 run(snapshots, history) 返回 list[Alert]
- 触发器以装饰器注册到 TRIGGERS，按 rule_id 索引
- 阈值集中在 data/alert_config.json，PM 可独立调整
- 去重 / 用户忽略 / 严重度排序在编排层统一处理
- 统一向 Alert.payload 写入 rule_id / metric / value / baseline，方便 UI 审计
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from data_pipeline.schema import Alert, CompetitorSnapshot

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ALERT_CONFIG_PATH = DATA_DIR / "alert_config.json"
ALERT_DISMISSED_PATH = DATA_DIR / "alert_dismissed.json"

# 版本更新关键词（迁移自 aggregator）
VERSION_FEATURE_KEYWORDS = [
    "功能", "feature", "new", "更新", "上线", "新增", "redesign", "redesigned",
    "widget", "widgets", "multiview", "lineup", "depth chart", "insight",
    "AI", "ai", "智能", "分析", "统计", "stat", "数据",
]

DEFAULT_CONFIG: dict = {
    "version": 1,
    "rules": {
        # 现有 4 条规则（Phase A）
        "negative_review": {"enabled": True, "severity": "danger"},
        "rank_rise_wow": {"enabled": True, "threshold": 10, "severity": "warn"},
        "version_feature": {"enabled": True, "severity": "danger"},
        "commercial_price_change": {"enabled": True, "severity": "danger"},
        "commercial_iap_change": {"enabled": True, "severity": "warn"},
        "commercial_betting": {"enabled": True, "severity": "warn"},
        # P0 规则（Phase C）— 默认启用，依赖历史数据
        "rank_jump_abs": {"enabled": True, "threshold": 20, "severity": "danger"},
        "rank_jump_streak": {"enabled": True, "delta": 10, "days": 3, "severity": "warn"},
        "rank_baseline_drift": {"enabled": True, "threshold": 15, "severity": "warn"},
        "review_volume_spike": {"enabled": True, "k_sigma": 2.0, "min_history": 7, "severity": "warn"},
        "review_negative_burst": {"enabled": True, "k_sigma": 2.0, "min_history": 7, "severity": "danger"},
        "review_negative_ratio": {"enabled": True, "threshold": 0.5, "min_total": 5, "severity": "danger"},
        "social_negative_ratio": {"enabled": True, "threshold": 0.5, "min_total": 10, "severity": "danger"},
        "social_alert_level": {"enabled": True, "severity": "danger"},
        "social_pain_severity": {"enabled": True, "min_severity": 4, "severity": "warn"},
        # P1 规则（Phase D）
        "product_update_spike": {"enabled": True, "k_sigma": 2.0, "min_history": 7, "severity": "warn"},
        "product_bugfix_spike": {"enabled": True, "k_sigma": 2.0, "min_history": 7, "severity": "warn"},
        "ad_volume_spike": {"enabled": True, "k_sigma": 2.0, "min_history": 7, "severity": "warn"},
        "ad_pacing_anomaly": {"enabled": True, "z_threshold": 2.0, "min_history": 7, "severity": "warn"},
        "iap_revenue_drift": {"enabled": True, "threshold_pct": 0.30, "severity": "danger"},
        "download_daily_spike": {"enabled": True, "k_sigma": 2.0, "min_history": 7, "severity": "warn"},
        "download_weekly_spike": {"enabled": True, "k_sigma": 3.0, "min_history": 14, "severity": "danger"},
    },
    "global": {
        "dedup_window_hours": 24,
        "cold_start_days": 7,
        "max_alerts_per_run": 200,
    },
}


# ---------------------------------------------------------------------------
# 触发器注册
# ---------------------------------------------------------------------------

TRIGGERS: dict[str, Callable[["AlertContext"], list[Alert]]] = {}


def trigger(rule_id: str):
    """装饰器：注册 rule_id → 函数。"""

    def deco(fn: Callable[["AlertContext"], list[Alert]]):
        TRIGGERS[rule_id] = fn
        return fn

    return deco


@dataclass
class AlertContext:
    snapshots: dict[str, CompetitorSnapshot]
    config: dict
    history: dict = field(default_factory=dict)
    today: str = ""

    def rule_cfg(self, rule_id: str) -> dict:
        return self.config.get("rules", {}).get(rule_id, {})

    def rule_enabled(self, rule_id: str) -> bool:
        cfg = self.rule_cfg(rule_id)
        return bool(cfg.get("enabled", True))

    def rule_severity(self, rule_id: str, default: str = "warn") -> str:
        return self.rule_cfg(rule_id).get("severity", default)


# ---------------------------------------------------------------------------
# 历史基线工具（Phase B 详细实现，A 阶段先放占位）
# ---------------------------------------------------------------------------


def baseline_stats(values: list[float]) -> dict:
    """返回 {n, mean, std}。空值或单点时 std=0。"""
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0}
    if n == 1:
        return {"n": 1, "mean": vals[0], "std": 0.0}
    mean = statistics.fmean(vals)
    std = statistics.pstdev(vals)
    return {"n": n, "mean": mean, "std": std}


def z_score(value: float, stats: dict) -> float | None:
    if not stats or stats.get("std", 0) <= 0:
        return None
    return (float(value) - stats["mean"]) / stats["std"]


def is_cold_start(stats: dict, min_history: int) -> bool:
    return stats.get("n", 0) < int(min_history)


# ---------------------------------------------------------------------------
# History 取数器（按 metric × competitor 提取时序）
# ---------------------------------------------------------------------------


def _rank_history_for(history: dict, app_id) -> list[tuple[str, int]]:
    """ranking_history → [(date, rank)] 按日期升序，仅 rank 为整数的项。"""
    if not app_id:
        return []
    rh = history.get("ranking_history") or {}
    out: list[tuple[str, int]] = []
    for d in sorted(rh.keys()):
        r = (rh.get(d) or {}).get(str(app_id))
        if isinstance(r, (int, float)):
            out.append((d, int(r)))
    return out


def _market_history_daily(history: dict, name: str, field: str) -> list[tuple[str, float]]:
    """market_history.csv → 按日期汇总（每日取最后一条非空值），升序。"""
    rows = history.get("market_history") or []
    by_date: dict[str, float] = {}
    for r in rows:
        if r.get("app") != name:
            continue
        ts = (r.get("timestamp") or "")[:10]
        if not ts:
            continue
        v = r.get(field)
        if v in (None, "", "nan"):
            continue
        try:
            by_date[ts] = float(v)  # 后值覆盖，等价取当日最后一条
        except (ValueError, TypeError):
            continue
    return sorted(by_date.items(), key=lambda x: x[0])


def _commercial_history_for(history: dict, name: str) -> list[tuple[str, dict]]:
    """commercial_history → [(date, comp_dict)]，结构 {date: {name: {...}}}。"""
    ch = history.get("commercial_history") or {}
    out: list[tuple[str, dict]] = []
    for d in sorted(ch.keys()):
        bucket = ch.get(d) or {}
        comp = None
        if isinstance(bucket, dict):
            if name in bucket and isinstance(bucket[name], dict):
                comp = bucket[name]
            elif "competitors" in bucket and isinstance(bucket["competitors"], dict):
                comp = bucket["competitors"].get(name)
        if comp:
            out.append((d, comp))
    return out


def _ads_daily_trend(snap: CompetitorSnapshot) -> list[tuple[str, int]]:
    """从 snap.commercial.ads.daily_trend 取 [(date, count)] 升序。"""
    trend = (snap.commercial.ads.daily_trend if snap.commercial and snap.commercial.ads else None) or []
    out: list[tuple[str, int]] = []
    for r in trend:
        d = r.get("date") or r.get("day")
        c = r.get("count") or r.get("active_count") or r.get("new_ads") or 0
        if d:
            try:
                out.append((str(d), int(c)))
            except (ValueError, TypeError):
                continue
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------------------
# 现有 4 条规则迁移（Phase A 行为零差异）
# ---------------------------------------------------------------------------


@trigger("negative_review")
def _t_negative_review(ctx: AlertContext) -> list[Alert]:
    if not ctx.rule_enabled("negative_review"):
        return []
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        if snap.comments.negative <= 0:
            continue
        label_counter = Counter(snap.comments.labels)
        top = "、".join(f"{lab}({c}条)" for lab, c in label_counter.most_common(3))
        out.append(
            Alert(
                type="negative_review",
                severity=ctx.rule_severity("negative_review", "danger"),
                severity_label="高威胁",
                icon="",
                title=f"{name} 出现低星评论",
                desc=(
                    f"近 3 天检测到 {snap.comments.negative} 条低星评论，"
                    f"共抓取 {snap.comments.total} 条评论。"
                    f"高频信号：{top or '暂无标签分布'}。"
                ),
                time="今天",
                competitor=name,
                payload={
                    "rule_id": "negative_review",
                    "metric": "comments.negative",
                    "value": snap.comments.negative,
                    "total": snap.comments.total,
                    "top_labels": list(label_counter.most_common(3)),
                    "module": "review",
                    "date": ctx.today,
                },
            )
        )
    return out


@trigger("rank_rise_wow")
def _t_rank_rise_wow(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("rank_rise_wow")
    if not cfg.get("enabled", True):
        return []
    threshold = int(cfg.get("threshold", 10))
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        delta = snap.rank.delta_wow
        if delta is None or delta <= threshold:
            continue
        old = (snap.rank.current or 0) + delta
        out.append(
            Alert(
                type="rank_rise",
                severity=cfg.get("severity", "warn"),
                severity_label="中威胁",
                icon="",
                title=f"{name} 排名快速上升 {delta} 位",
                desc=(
                    f"一周内从 #{old} 上升至 #{snap.rank.current}，"
                    f"上升 {delta} 位，买量或功能更新信号明显。"
                ),
                time="本周",
                competitor=name,
                payload={
                    "rule_id": "rank_rise_wow",
                    "metric": "rank.delta_wow",
                    "value": delta,
                    "old_rank": old,
                    "new_rank": snap.rank.current,
                    "delta": delta,
                    "threshold": threshold,
                    "module": "rank",
                    "date": ctx.today,
                },
            )
        )
    return out


@trigger("version_feature")
def _t_version_feature(ctx: AlertContext) -> list[Alert]:
    if not ctx.rule_enabled("version_feature"):
        return []
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
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
        out.append(
            Alert(
                type="version_update",
                severity=ctx.rule_severity("version_feature", "danger"),
                severity_label="高威胁 · 建议评估",
                icon="",
                title=f"{name} 版本更新至 v{v.current or '未知'}，涉及功能变更",
                desc=change_summary,
                time="今天",
                competitor=name,
                payload={
                    "rule_id": "version_feature",
                    "metric": "version.has_feature",
                    "value": v.current,
                    "version": v.current,
                    "change_type": v.change_type,
                    "change_tags": list(v.change_tags or []),
                    "changes": list(v.changes or [])[:5],
                    "module": "product",
                    "date": ctx.today,
                },
            )
        )
    return out


@trigger("commercial_price_change")
def _t_commercial_price_change(ctx: AlertContext) -> list[Alert]:
    if not ctx.rule_enabled("commercial_price_change"):
        return []
    out: list[Alert] = []
    sev = ctx.rule_severity("commercial_price_change", "danger")
    for name, snap in ctx.snapshots.items():
        for pa in snap.commercial.price_alerts or []:
            out.append(
                Alert(
                    type="commercial_change",
                    severity=sev,
                    severity_label="高威胁",
                    icon="",
                    title=f"{name} IAP {pa.get('direction', '变动')}: {pa.get('name', '')}",
                    desc=(
                        f"价格从 ${pa.get('prev', 0)} 变为 ${pa.get('curr', 0)}"
                        f"（{pa.get('direction', '')} ${abs(pa.get('delta', 0))}）"
                    ),
                    time="今天",
                    competitor=name,
                    payload={
                        "rule_id": "commercial_price_change",
                        "metric": "commercial.price",
                        "value": pa.get("curr"),
                        "prev": pa.get("prev"),
                        "delta": pa.get("delta"),
                        "direction": pa.get("direction"),
                        "iap_name": pa.get("name"),
                        "module": "commercial",
                        "date": ctx.today,
                        **{k: v for k, v in pa.items() if k not in {"prev", "curr", "delta", "direction", "name"}},
                    },
                )
            )
    return out


@trigger("commercial_iap_change")
def _t_commercial_iap_change(ctx: AlertContext) -> list[Alert]:
    if not ctx.rule_enabled("commercial_iap_change"):
        return []
    out: list[Alert] = []
    sev = ctx.rule_severity("commercial_iap_change", "warn")
    for name, snap in ctx.snapshots.items():
        for ic in snap.commercial.iap_changes or []:
            out.append(
                Alert(
                    type="commercial_change",
                    severity=sev,
                    severity_label="中威胁",
                    icon="",
                    title=f"{name} IAP {ic.get('type', '变动')}: {ic.get('name', '')}",
                    desc=(
                        f"检测到内购项「{ic.get('name', '')}」{ic.get('type', '变动')}，"
                        f"建议关注竞品商业策略调整。"
                    ),
                    time="今天",
                    competitor=name,
                    payload={
                        "rule_id": "commercial_iap_change",
                        "metric": "commercial.iap_changes",
                        "value": ic.get("name"),
                        "iap_type": ic.get("type"),
                        "iap_name": ic.get("name"),
                        "module": "commercial",
                        "date": ctx.today,
                        **{k: v for k, v in ic.items() if k not in {"type", "name"}},
                    },
                )
            )
    return out


@trigger("commercial_betting")
def _t_commercial_betting(ctx: AlertContext) -> list[Alert]:
    if not ctx.rule_enabled("commercial_betting"):
        return []
    out: list[Alert] = []
    sev = ctx.rule_severity("commercial_betting", "warn")
    for name, snap in ctx.snapshots.items():
        c = snap.commercial
        if not c.betting_signals:
            continue
        out.append(
            Alert(
                type="commercial_change",
                severity=sev,
                severity_label="中威胁",
                icon="",
                title=f"{name} 检测到博彩导流信号",
                desc=f"应用描述中包含博彩相关关键词: {', '.join(c.description_keywords or [])}",
                time="今天",
                competitor=name,
                payload={
                    "rule_id": "commercial_betting",
                    "metric": "commercial.betting_signals",
                    "value": True,
                    "keywords": list(c.description_keywords or []),
                    "module": "commercial",
                    "date": ctx.today,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Phase C 规则：排名 / 评论 / 社媒
# ---------------------------------------------------------------------------


@trigger("rank_jump_abs")
def _t_rank_jump_abs(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("rank_jump_abs")
    if not cfg.get("enabled", True):
        return []
    threshold = int(cfg.get("threshold", 20))
    sev = cfg.get("severity", "danger")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        series = _rank_history_for(ctx.history, snap.rank.app_id)
        if len(series) < 2:
            continue
        d_prev, r_prev = series[-2]
        d_cur, r_cur = series[-1]
        if r_cur > 100 and r_prev > 100:
            continue  # Top100 外
        delta = r_prev - r_cur  # 正 = 上升
        if abs(delta) < threshold:
            continue
        direction = "上升" if delta > 0 else "下降"
        out.append(
            Alert(
                type="rank_jump",
                severity=sev,
                severity_label="高威胁" if sev == "danger" else "中威胁",
                icon="",
                title=f"{name} 排名单日{direction} {abs(delta)} 位",
                desc=f"{d_prev} #{r_prev} → {d_cur} #{r_cur}（Δ {delta:+d}），触发单日跳变阈值 ±{threshold}。",
                time=d_cur,
                competitor=name,
                payload={
                    "rule_id": "rank_jump_abs",
                    "metric": "rank.daily_delta",
                    "value": delta,
                    "old_rank": r_prev,
                    "new_rank": r_cur,
                    "threshold": threshold,
                    "module": "rank",
                    "date": d_cur,
                    "trend": [{"date": d, "value": v} for d, v in series[-30:]],
                },
            )
        )
    return out


@trigger("rank_jump_streak")
def _t_rank_jump_streak(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("rank_jump_streak")
    if not cfg.get("enabled", True):
        return []
    delta_min = int(cfg.get("delta", 10))
    days = int(cfg.get("days", 3))
    sev = cfg.get("severity", "warn")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        series = _rank_history_for(ctx.history, snap.rank.app_id)
        if len(series) < days + 1:
            continue
        recent = series[-(days + 1):]
        deltas = [recent[i + 1][1] - recent[i][1] for i in range(days)]
        # 同方向：全负 = 持续上升（rank 数字下降），全正 = 持续下降
        all_up = all(d <= -delta_min for d in deltas)
        all_down = all(d >= delta_min for d in deltas)
        if not (all_up or all_down):
            continue
        direction = "上升" if all_up else "下降"
        total = recent[-1][1] - recent[0][1]
        out.append(
            Alert(
                type="rank_jump",
                severity=sev,
                severity_label="中威胁",
                icon="",
                title=f"{name} 连续 {days} 天{direction}（累计 {abs(total)} 位）",
                desc=f"近 {days} 天每日变动 ≥ {delta_min} 位且方向一致，{recent[0][0]} #{recent[0][1]} → {recent[-1][0]} #{recent[-1][1]}。",
                time=recent[-1][0],
                competitor=name,
                payload={
                    "rule_id": "rank_jump_streak",
                    "metric": "rank.streak",
                    "value": abs(total),
                    "days": days,
                    "delta_min": delta_min,
                    "deltas": deltas,
                    "module": "rank",
                    "date": recent[-1][0],
                    "trend": [{"date": d, "value": v} for d, v in series[-30:]],
                },
            )
        )
    return out


@trigger("rank_baseline_drift")
def _t_rank_baseline_drift(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("rank_baseline_drift")
    if not cfg.get("enabled", True):
        return []
    threshold = int(cfg.get("threshold", 15))
    sev = cfg.get("severity", "warn")
    market = (ctx.history.get("market_rank") or {})
    baseline_app = market.get("baseline_app")
    baseline_label = market.get("baseline_label") or baseline_app or "All Football"
    comparison = market.get("baseline_comparison") or {}
    if not (baseline_app and comparison):
        return []
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        if name == baseline_app:
            continue
        cmp = comparison.get(name) or {}
        diff = cmp.get("rank_diff") or cmp.get("delta") or cmp.get("vs_baseline")
        if diff is None:
            continue
        try:
            diff_v = int(diff)
        except (ValueError, TypeError):
            continue
        if abs(diff_v) <= threshold:
            continue
        direction = "领先" if diff_v < 0 else "落后"
        out.append(
            Alert(
                type="rank_drift",
                severity=sev,
                severity_label="中威胁",
                icon="",
                title=f"{name} 相对 {baseline_label} {direction} {abs(diff_v)} 位",
                desc=f"当前竞品排名相对基线 {baseline_label} 偏离 {diff_v:+d}（阈值 ±{threshold}）。",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "rank_baseline_drift",
                    "metric": "rank.baseline_diff",
                    "value": diff_v,
                    "baseline_app": baseline_app,
                    "threshold": threshold,
                    "module": "rank",
                    "date": ctx.today,
                },
            )
        )
    return out


@trigger("review_volume_spike")
def _t_review_volume_spike(ctx: AlertContext) -> list[Alert]:
    """评论数 vs 历史均值 × k_sigma：当前快照只有"今日"评论数，无每日历史。
    退化为：本周 total > 30 时给信息提示（cold-start 兜底）。"""
    cfg = ctx.rule_cfg("review_volume_spike")
    if not cfg.get("enabled", True):
        return []
    # 当前阶段无评论时序数据 → 仅在本周 total ≥ 50 时触发
    sev = cfg.get("severity", "warn")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        total = snap.comments.total or 0
        if total < 50:
            continue
        out.append(
            Alert(
                type="review_volume",
                severity=sev,
                severity_label="中威胁",
                icon="",
                title=f"{name} 本期评论量较高（{total} 条）",
                desc=f"近期共抓取 {total} 条用户评论，建议关注主题分布。"
                f"（注：评论时序基线尚未建立，规则按硬阈值 50 条触发）",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "review_volume_spike",
                    "metric": "comments.total",
                    "value": total,
                    "module": "review",
                    "date": ctx.today,
                    "cold_start": True,
                },
            )
        )
    return out


@trigger("review_negative_burst")
def _t_review_negative_burst(ctx: AlertContext) -> list[Alert]:
    """负面评论量异常爆发。同 volume，无历史时退化硬阈值（≥ 10 条）。"""
    cfg = ctx.rule_cfg("review_negative_burst")
    if not cfg.get("enabled", True):
        return []
    sev = cfg.get("severity", "danger")
    threshold_abs = 10
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        neg = snap.comments.negative or 0
        if neg < threshold_abs:
            continue
        # 排除 negative_review 本身覆盖的简单情况（payload 区分）
        out.append(
            Alert(
                type="review_negative_burst",
                severity=sev,
                severity_label="高威胁",
                icon="",
                title=f"{name} 负面评论激增（{neg} 条）",
                desc=f"近期共出现 {neg} 条低星 / 负面评论，超过硬阈值 {threshold_abs}。"
                f"建议立即介入排查具体反馈。",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "review_negative_burst",
                    "metric": "comments.negative",
                    "value": neg,
                    "threshold": threshold_abs,
                    "module": "review",
                    "date": ctx.today,
                    "cold_start": True,
                },
            )
        )
    return out


@trigger("review_negative_ratio")
def _t_review_negative_ratio(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("review_negative_ratio")
    if not cfg.get("enabled", True):
        return []
    threshold = float(cfg.get("threshold", 0.5))
    min_total = int(cfg.get("min_total", 5))
    sev = cfg.get("severity", "danger")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        total = snap.comments.total or 0
        neg = snap.comments.negative or 0
        if total < min_total:
            continue
        ratio = neg / total
        if ratio < threshold:
            continue
        out.append(
            Alert(
                type="review_negative_ratio",
                severity=sev,
                severity_label="高威胁",
                icon="",
                title=f"{name} 负面评论占比 {round(ratio * 100)}%",
                desc=f"近期 {total} 条评论中 {neg} 条为负面（{round(ratio*100)}%），"
                f"超过阈值 {round(threshold*100)}%，需关注用户体验问题。",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "review_negative_ratio",
                    "metric": "comments.negative_ratio",
                    "value": round(ratio, 3),
                    "negative": neg,
                    "total": total,
                    "threshold": threshold,
                    "module": "review",
                    "date": ctx.today,
                },
            )
        )
    return out


@trigger("social_negative_ratio")
def _t_social_negative_ratio(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("social_negative_ratio")
    if not cfg.get("enabled", True):
        return []
    threshold = float(cfg.get("threshold", 0.5))
    min_total = int(cfg.get("min_total", 10))
    sev = cfg.get("severity", "danger")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        ai = snap.community.ai_analysis if snap.community else None
        raw = snap.community.raw if snap.community else None
        if not ai or not ai.sentiment:
            continue
        total = (raw.mention_count if raw else 0) or 0
        if total < min_total:
            continue
        neg = float(ai.sentiment.get("negative") or 0)
        if neg < threshold:
            continue
        out.append(
            Alert(
                type="social_negative",
                severity=sev,
                severity_label="高威胁",
                icon="",
                title=f"{name} 社媒负面情绪占比 {round(neg * 100)}%",
                desc=f"基于 {total} 条社媒讨论，AI 判定负面情绪占 {round(neg*100)}%（阈值 {round(threshold*100)}%），"
                f"建议查看痛点详情。",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "social_negative_ratio",
                    "metric": "community.sentiment.negative",
                    "value": round(neg, 3),
                    "total": total,
                    "threshold": threshold,
                    "module": "community",
                    "date": ctx.today,
                },
            )
        )
    return out


@trigger("social_alert_level")
def _t_social_alert_level(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("social_alert_level")
    if not cfg.get("enabled", True):
        return []
    sev = cfg.get("severity", "danger")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        ai = snap.community.ai_analysis if snap.community else None
        if not ai or (ai.alert_level or "").lower() != "high":
            continue
        out.append(
            Alert(
                type="social_alert",
                severity=sev,
                severity_label="高威胁",
                icon="",
                title=f"{name} 社媒 AI 判定为高风险",
                desc=(ai.overall_summary or "")[:140] or "AI 在社媒讨论中检测到高风险信号。",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "social_alert_level",
                    "metric": "community.ai.alert_level",
                    "value": ai.alert_level,
                    "module": "community",
                    "date": ctx.today,
                    "ai_summary": ai.overall_summary,
                    "top_topics": list(ai.top_topics or []),
                },
            )
        )
    return out


@trigger("social_pain_severity")
def _t_social_pain_severity(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("social_pain_severity")
    if not cfg.get("enabled", True):
        return []
    min_sev = int(cfg.get("min_severity", 4))
    sev = cfg.get("severity", "warn")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        ai = snap.community.ai_analysis if snap.community else None
        if not ai:
            continue
        pains = ai.pain_points_with_severity or []
        hits = [p for p in pains if int(p.get("severity") or 0) >= min_sev]
        if not hits:
            continue
        top = hits[0]
        out.append(
            Alert(
                type="social_pain",
                severity=sev,
                severity_label="中威胁",
                icon="",
                title=f"{name} 出现高严重度社媒痛点（severity ≥ {min_sev}）",
                desc=f"代表痛点：「{top.get('topic') or top.get('theme') or '未分类'}」"
                f"（severity {top.get('severity')}, frequency {top.get('frequency') or top.get('count')}）。",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "social_pain_severity",
                    "metric": "community.pain.severity",
                    "value": top.get("severity"),
                    "module": "community",
                    "date": ctx.today,
                    "pains": hits[:5],
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Phase D 规则：产品 / 广告 / IAP / 下载
# ---------------------------------------------------------------------------


@trigger("product_update_spike")
def _t_product_update_spike(ctx: AlertContext) -> list[Alert]:
    """周内 has_changed=True 的竞品较多（无每竞品历史，全局硬阈值）。"""
    cfg = ctx.rule_cfg("product_update_spike")
    if not cfg.get("enabled", True):
        return []
    sev = cfg.get("severity", "warn")
    strategy = ctx.history.get("strategy") or {}
    competitors = strategy.get("competitors") or {}
    changed = sum(1 for v in competitors.values() if isinstance(v, dict) and v.get("has_changed"))
    if changed < 3:  # 硬阈值：本周 3 家以上同时更新
        return []
    # 输出全局告警（competitor 留空指向行业层面）
    return [
        Alert(
            type="product_update_spike",
            severity=sev,
            severity_label="中威胁",
            icon="",
            title=f"本期 {changed} 家竞品同步发布版本更新",
            desc="多家竞品在同一时段内集中迭代，可能存在共同节奏（行业事件 / 节日 / 平台政策）。",
            time=ctx.today,
            competitor="行业",
            payload={
                "rule_id": "product_update_spike",
                "metric": "strategy.changed_count",
                "value": changed,
                "module": "product",
                "date": ctx.today,
                "changed_competitors": [n for n, v in competitors.items() if isinstance(v, dict) and v.get("has_changed")],
            },
        )
    ]


@trigger("product_bugfix_spike")
def _t_product_bugfix_spike(ctx: AlertContext) -> list[Alert]:
    """单竞品本期更新中 bugfix 标签 ≥ 2 → 触发（无历史时）。"""
    cfg = ctx.rule_cfg("product_bugfix_spike")
    if not cfg.get("enabled", True):
        return []
    sev = cfg.get("severity", "warn")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        v = snap.version
        tags = v.change_tags or []
        bugfix_hits = sum(1 for t in tags if "bug" in str(t).lower() or "修复" in str(t))
        if bugfix_hits < 2:
            continue
        out.append(
            Alert(
                type="product_bugfix",
                severity=sev,
                severity_label="中威胁",
                icon="",
                title=f"{name} 本期 bugfix 集中（{bugfix_hits} 条）",
                desc=f"版本 v{v.current} 包含 {bugfix_hits} 条修复类标签，可能在解决稳定性问题。",
                time=ctx.today,
                competitor=name,
                payload={
                    "rule_id": "product_bugfix_spike",
                    "metric": "version.bugfix_count",
                    "value": bugfix_hits,
                    "module": "product",
                    "date": ctx.today,
                    "change_tags": list(tags),
                },
            )
        )
    return out


@trigger("ad_volume_spike")
def _t_ad_volume_spike(ctx: AlertContext) -> list[Alert]:
    """新增广告量 ≥ μ × k_sigma；冷启动时按 active_count 硬阈值。"""
    cfg = ctx.rule_cfg("ad_volume_spike")
    if not cfg.get("enabled", True):
        return []
    k = float(cfg.get("k_sigma", 2.0))
    min_history = int(cfg.get("min_history", 7))
    sev = cfg.get("severity", "warn")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        ads = snap.commercial.ads if snap.commercial else None
        if not ads:
            continue
        series = _ads_daily_trend(snap)
        if len(series) >= min_history + 1:
            history_vals = [v for _, v in series[:-1]]
            today_v = series[-1][1]
            stats = baseline_stats(history_vals)
            z = z_score(today_v, stats)
            if z is not None and z >= k:
                out.append(
                    Alert(
                        type="ad_volume",
                        severity=sev,
                        severity_label="中威胁",
                        icon="",
                        title=f"{name} 当日广告投放数飙升（{today_v}）",
                        desc=f"近 {stats['n']} 天均值 {stats['mean']:.1f}，今日 {today_v}（z={z:.1f}），"
                        f"超过阈值 k={k}。",
                        time=series[-1][0],
                        competitor=name,
                        payload={
                            "rule_id": "ad_volume_spike",
                            "metric": "ads.daily_count",
                            "value": today_v,
                            "baseline": stats,
                            "z": round(z, 2),
                            "k": k,
                            "module": "ads",
                            "date": series[-1][0],
                            "trend": [{"date": d, "value": v} for d, v in series[-30:]],
                        },
                    )
                )
            continue
        # 冷启动：active_count ≥ 50 兜底
        if (ads.active_count or 0) >= 50 and (ads.new_ads or 0) >= 10:
            out.append(
                Alert(
                    type="ad_volume",
                    severity=sev,
                    severity_label="中威胁",
                    icon="",
                    title=f"{name} 当前广告活跃度较高",
                    desc=f"active_count={ads.active_count}, new_ads={ads.new_ads}（冷启动兜底阈值）。",
                    time=ctx.today,
                    competitor=name,
                    payload={
                        "rule_id": "ad_volume_spike",
                        "metric": "ads.active_count",
                        "value": ads.active_count,
                        "new_ads": ads.new_ads,
                        "module": "ads",
                        "date": ctx.today,
                        "cold_start": True,
                    },
                )
            )
    return out


@trigger("ad_pacing_anomaly")
def _t_ad_pacing_anomaly(ctx: AlertContext) -> list[Alert]:
    """active_count z-score |>2|（基于 daily_trend）。"""
    cfg = ctx.rule_cfg("ad_pacing_anomaly")
    if not cfg.get("enabled", True):
        return []
    z_th = float(cfg.get("z_threshold", 2.0))
    min_history = int(cfg.get("min_history", 7))
    sev = cfg.get("severity", "warn")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        series = _ads_daily_trend(snap)
        if len(series) < min_history + 1:
            continue
        history_vals = [v for _, v in series[:-1]]
        today_v = series[-1][1]
        stats = baseline_stats(history_vals)
        z = z_score(today_v, stats)
        if z is None or abs(z) < z_th:
            continue
        direction = "上升" if z > 0 else "下降"
        out.append(
            Alert(
                type="ad_pacing",
                severity=sev,
                severity_label="中威胁",
                icon="",
                title=f"{name} 广告投放节奏{direction}异常（z={z:+.1f}）",
                desc=f"基线 μ={stats['mean']:.1f} σ={stats['std']:.1f}，今日 {today_v}，"
                f"|z| 超过阈值 {z_th}。",
                time=series[-1][0],
                competitor=name,
                payload={
                    "rule_id": "ad_pacing_anomaly",
                    "metric": "ads.pacing_z",
                    "value": round(z, 2),
                    "baseline": stats,
                    "today_value": today_v,
                    "module": "ads",
                    "date": series[-1][0],
                    "trend": [{"date": d, "value": v} for d, v in series[-30:]],
                },
            )
        )
    return out


@trigger("iap_revenue_drift")
def _t_iap_revenue_drift(ctx: AlertContext) -> list[Alert]:
    cfg = ctx.rule_cfg("iap_revenue_drift")
    if not cfg.get("enabled", True):
        return []
    pct = float(cfg.get("threshold_pct", 0.30))
    sev = cfg.get("severity", "danger")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        series = _market_history_daily(ctx.history, name, "revenue_proxy")
        if len(series) < 8:
            continue
        # 周对比：今天 vs 7 天前
        today_d, today_v = series[-1]
        if today_v == 0:
            continue
        # 找 7 天前最近的点
        from datetime import datetime as _dt, timedelta as _td

        try:
            base_dt = _dt.fromisoformat(today_d) - _td(days=7)
        except ValueError:
            continue
        prev_v = None
        prev_d = None
        for d, v in reversed(series[:-1]):
            try:
                if _dt.fromisoformat(d) <= base_dt:
                    prev_v = v
                    prev_d = d
                    break
            except ValueError:
                continue
        if prev_v is None or prev_v == 0:
            prev_d, prev_v = series[0]
        delta_pct = (today_v - prev_v) / prev_v
        if abs(delta_pct) < pct:
            continue
        direction = "上升" if delta_pct > 0 else "下降"
        out.append(
            Alert(
                type="iap_revenue",
                severity=sev,
                severity_label="高威胁",
                icon="",
                title=f"{name} 收入代理周{direction} {round(abs(delta_pct)*100)}%",
                desc=f"{prev_d} {prev_v:.0f} → {today_d} {today_v:.0f}（Δ {delta_pct:+.1%}），"
                f"超过阈值 ±{round(pct*100)}%。",
                time=today_d,
                competitor=name,
                payload={
                    "rule_id": "iap_revenue_drift",
                    "metric": "market_history.revenue_proxy",
                    "value": today_v,
                    "prev": prev_v,
                    "delta_pct": round(delta_pct, 3),
                    "threshold_pct": pct,
                    "module": "iap",
                    "date": today_d,
                    "trend": [{"date": d, "value": v} for d, v in series[-30:]],
                },
            )
        )
    return out


def _download_spike_helper(ctx: AlertContext, rule_id: str, days: int) -> list[Alert]:
    cfg = ctx.rule_cfg(rule_id)
    if not cfg.get("enabled", True):
        return []
    k = float(cfg.get("k_sigma", 2.0))
    min_history = int(cfg.get("min_history", 7))
    sev = cfg.get("severity", "warn")
    out: list[Alert] = []
    for name, snap in ctx.snapshots.items():
        series = _market_history_daily(ctx.history, name, "download_proxy")
        if len(series) < min_history + 1:
            continue
        if days == 1:
            today_v = series[-1][1]
            history_vals = [v for _, v in series[:-1]]
        else:
            # 周对比：取最近 7 天均值与之前的均值对比
            if len(series) < days + min_history:
                continue
            recent = [v for _, v in series[-days:]]
            history_vals = [v for _, v in series[:-days]]
            today_v = sum(recent) / len(recent)
        stats = baseline_stats(history_vals)
        z = z_score(today_v, stats)
        if z is None or abs(z) < k:
            continue
        direction = "上升" if z > 0 else "下降"
        title_unit = "单日" if days == 1 else f"近 {days} 天"
        out.append(
            Alert(
                type="download_spike",
                severity=sev,
                severity_label="高威胁" if sev == "danger" else "中威胁",
                icon="",
                title=f"{name} 下载量{title_unit}{direction}异常（z={z:+.1f}）",
                desc=f"基线 μ={stats['mean']:.0f} σ={stats['std']:.0f}，当前 {today_v:.0f}，"
                f"|z| 超阈值 k={k}。",
                time=series[-1][0],
                competitor=name,
                payload={
                    "rule_id": rule_id,
                    "metric": "market_history.download_proxy",
                    "value": today_v,
                    "baseline": stats,
                    "z": round(z, 2),
                    "k": k,
                    "window_days": days,
                    "module": "download",
                    "date": series[-1][0],
                    "trend": [{"date": d, "value": v} for d, v in series[-30:]],
                },
            )
        )
    return out


@trigger("download_daily_spike")
def _t_download_daily_spike(ctx: AlertContext) -> list[Alert]:
    return _download_spike_helper(ctx, "download_daily_spike", days=1)


@trigger("download_weekly_spike")
def _t_download_weekly_spike(ctx: AlertContext) -> list[Alert]:
    return _download_spike_helper(ctx, "download_weekly_spike", days=7)


# ---------------------------------------------------------------------------
# 编排：去重 / 忽略 / 排序 / 上限
# ---------------------------------------------------------------------------


def _alert_fingerprint(a: Alert) -> str:
    rule = (a.payload or {}).get("rule_id") or a.type
    day = ((a.payload or {}).get("date") or a.time or "")[:10]
    return f"{rule}|{a.competitor}|{day}"


SEVERITY_RANK = {"danger": 0, "warn": 1, "info": 2}


def _apply_dismissed(alerts: list[Alert]) -> list[Alert]:
    if not ALERT_DISMISSED_PATH.exists():
        return alerts
    try:
        data = json.loads(ALERT_DISMISSED_PATH.read_text(encoding="utf-8"))
        dismissed = set(data) if isinstance(data, list) else set(data.get("ids", []))
    except Exception:
        return alerts
    return [a for a in alerts if _alert_fingerprint(a) not in dismissed]


def _dedup(alerts: list[Alert]) -> list[Alert]:
    """同 (rule, comp, day) 保留最高 severity。"""
    seen: dict[str, Alert] = {}
    for a in alerts:
        fp = _alert_fingerprint(a)
        prev = seen.get(fp)
        if prev is None:
            seen[fp] = a
            continue
        if SEVERITY_RANK.get(a.severity, 99) < SEVERITY_RANK.get(prev.severity, 99):
            seen[fp] = a
    return list(seen.values())


def _sort_and_cap(alerts: list[Alert], config: dict) -> list[Alert]:
    alerts.sort(key=lambda a: (SEVERITY_RANK.get(a.severity, 99), a.competitor))
    cap = int(config.get("global", {}).get("max_alerts_per_run", 200))
    return alerts[:cap]


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """读取 alert_config.json，缺失时写入 DEFAULT_CONFIG。"""
    if ALERT_CONFIG_PATH.exists():
        try:
            return json.loads(ALERT_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    ALERT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_CONFIG_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run(
    snapshots: dict[str, CompetitorSnapshot],
    history: dict | None = None,
    config: dict | None = None,
) -> list[Alert]:
    """统一入口。Phase A 行为与 aggregator._build_alerts 一致。"""
    cfg = config if config is not None else load_config()
    today = datetime.now().strftime("%Y-%m-%d")
    ctx = AlertContext(
        snapshots=snapshots,
        config=cfg,
        history=history or {},
        today=today,
    )

    alerts: list[Alert] = []
    for rule_id, fn in TRIGGERS.items():
        try:
            alerts.extend(fn(ctx))
        except Exception as e:  # noqa: BLE001
            import traceback

            print(f"[alert_engine] {rule_id} failed: {e}")
            traceback.print_exc()

    alerts = _apply_dismissed(alerts)
    alerts = _dedup(alerts)
    alerts = _sort_and_cap(alerts, cfg)
    return alerts
