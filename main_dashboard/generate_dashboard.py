#!/usr/bin/env python3
"""
INTEL-OPS 竞品情报看板 · HTML 生成器

数据源：单一聚合产物 data/dashboard_data.json（由 data_pipeline.aggregator 生成）。
模板：dashboard_template.html，build_*_html 函数零修改 —— 通过 adapter 从聚合数据派生
出旧的全局变量名（strategy_data / market_data / comment_data / ranking_history /
competitor_registry / competitor_details / weekly_review_data / commercial_data /
commercial_weekly_data），保持现有逻辑兼容。
"""

import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"
TEMPLATE_PATH = _SCRIPT_DIR / "dashboard_template.html"
OUTPUT_HTML = _SCRIPT_DIR / "dashboard.html"

# 使 data_pipeline 包可导入
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from data_pipeline.aggregator import build_dashboard_data, OUTPUT_PATH as _AGG_OUTPUT_PATH
from data_pipeline.schema import to_dict


# ---------------------------------------------------------------------------
# 数据加载（统一入口）
# ---------------------------------------------------------------------------

def load_json(filename):
    """保留：少数辅助函数仍按文件名读取（如临时调试）。"""
    fp = DATA_DIR / filename
    if not fp.exists():
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _ensure_dashboard_data():
    """触发聚合层，写入 data/dashboard_data.json，并返回 dict 供模板使用。"""
    data = build_dashboard_data()
    payload = to_dict(data)
    _AGG_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_AGG_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


# ---- Adapter：从聚合数据派生旧的数据视图 ----------------------------------

def _adapt_strategy(D):
    # 原始 strategy_monitor.json 不存在时，返回空——保持与旧版本"暂无产品动态"完全一致
    if not D["meta"]["data_freshness"].get("strategy"):
        return {"generated_at": None, "total_monitored": 0, "changes_detected": 0, "competitors": {}}
    competitors = {}
    for name, snap in D["competitors"].items():
        v = snap["version"]
        if v.get("error"):
            competitors[name] = {"error": v["error"]}
            continue
        # 仅当原始 strategy 数据中确实存在该竞品（任意 version 字段非空）才输出
        if not (v.get("current") or v.get("release_notes") or v.get("has_changed")
                or v.get("is_first_record") or v.get("changes")):
            continue
        competitors[name] = {
            "version": v.get("current") or "",
            "release_notes": v.get("release_notes") or "",
            "in_app_purchases": v.get("in_app_purchases") or [],
            "has_changed": bool(v.get("has_changed")),
            "is_first_record": bool(v.get("is_first_record")),
            "version_changed": bool(v.get("version_changed")),
            "iap_changed": False,
            "changes": list(v.get("changes") or []),
            "analysis": v.get("ai_analysis") or "",
        }
    return {
        "generated_at": D["meta"]["data_freshness"].get("strategy"),
        "total_monitored": D["metrics"]["monitored"],
        "changes_detected": D["metrics"]["changes_detected"],
        "competitors": competitors,
    }


def _adapt_market(D):
    if not D["meta"]["data_freshness"].get("rank"):
        return {}
    competitor_performance = {}
    for name, snap in D["competitors"].items():
        r = snap["rank"]
        if r.get("current") is not None or r.get("app_id"):
            competitor_performance[name] = {
                "rank": r.get("current"),
                "delta": r.get("delta_dod"),
                "app_id": r.get("app_id"),
            }
    baseline = D.get("baseline") or {}
    return {
        "generated_at": D["meta"]["data_freshness"].get("rank"),
        "competitor_performance": competitor_performance,
        "leaderboard": list(D.get("leaderboard") or []),
        "fast_movers": list(D.get("fast_movers") or []),
        "new_contenders": list(D.get("new_contenders") or []),
        "ai_brief": D.get("ai_brief"),
        "multi_source": dict(D.get("multi_source") or {}),
        "baseline_app": baseline.get("app"),
        "baseline_label": baseline.get("label"),
        "baseline_comparison": dict(baseline.get("comparison") or {}),
    }


def _adapt_comments(D):
    if not D["meta"]["data_freshness"].get("comments"):
        return {}
    competitors = {}
    for name, snap in D["competitors"].items():
        regions = {}
        for code, r in (snap["comments"].get("by_region") or {}).items():
            regions[code] = {
                "count": r["count"],
                "negative_count": r["negative_count"],
                "labels": dict(r.get("labels") or {}),
                "summary": r.get("summary", ""),
                "reviews": list(r.get("reviews") or []),
            }
        if regions:
            competitors[name] = {"regions": regions}
    return {
        "generated_at": D["meta"]["data_freshness"].get("comments"),
        "competitors": competitors,
    }


def _adapt_ranking_history(D):
    out = {}
    for name, snap in D["competitors"].items():
        app_id = snap["rank"].get("app_id")
        if not app_id:
            continue
        for date, rank in (snap["rank"].get("history") or {}).items():
            out.setdefault(date, {})[str(app_id)] = rank
    return out


def _adapt_commercial(D):
    has_commercial = bool(D["meta"]["data_freshness"].get("commercial"))
    has_ads = any(
        (snap.get("commercial", {}).get("ads") or {}).get("active_count", 0) > 0
        for snap in (D.get("competitors") or {}).values()
    )
    if not has_commercial and not has_ads:
        return {}
    competitors = {}
    for name, snap in D["competitors"].items():
        c = snap["commercial"]
        ads_active = (c.get("ads") or {}).get("active_count") or 0
        # 至少一个商业相关字段非空（或有 Meta 广告投放）时才写入
        if any([c.get("monetization_tags"), c.get("iap_items"), c.get("price_alerts"),
                c.get("iap_changes"), c.get("betting_signals"), c.get("ai_intent"),
                c.get("rpd_index") is not None]) or ads_active > 0:
            competitors[name] = {
                "monetization_tags": list(c.get("monetization_tags") or []),
                "iap_items": list(c.get("iap_items") or []),
                "price_alerts": list(c.get("price_alerts") or []),
                "iap_changes": list(c.get("iap_changes") or []),
                "rpd_index": c.get("rpd_index"),
                "rank": c.get("rank"),
                "betting_signals": bool(c.get("betting_signals")),
                "description_keywords": list(c.get("description_keywords") or []),
                "seller_url": c.get("seller_url"),
                "ai_intent": c.get("ai_intent"),
                "ads": dict(c.get("ads") or {}),
            }
    return {
        "generated_at": D["meta"]["data_freshness"].get("commercial"),
        "competitors": competitors,
    }


def _adapt_community(D):
    """从 dashboard_data.competitors[*].community 派生 {<name>: {raw, ai_analysis, has_data}}。

    PRD v2：全部注册竞品都进 tab，无数据竞品由前端显示空态卡（避免"只显示 SofaScore"困惑）。
    """
    out = {}
    for name, snap in D["competitors"].items():
        c = snap.get("community") or {}
        raw = c.get("raw") or {}
        has_data = (raw.get("mention_count") or 0) > 0 or bool(c.get("ai_analysis"))
        out[name] = {
            "raw": raw,
            "ai_analysis": c.get("ai_analysis"),
            "has_data": has_data,
        }
    return out


def _adapt_product_updates(D):
    """直接透传 dashboard_data.product_updates（前端无需再转换）。"""
    return D.get("product_updates") or {"metrics": {}, "items": []}


def _adapt_reviews_analysis(D):
    """直接透传 dashboard_data.reviews_analysis。"""
    return D.get("reviews_analysis") or {"metrics": {}, "items": []}


def _adapt_rank_view(D):
    """给前端 page-ranking 用的扁平结构，避免 JS 到处找字段。

    包含：
    - leaderboard：透传 market_rank.leaderboard
    - baseline：透传 baseline.{app, label, comparison}
    - registry：透传 competitors.json，给"数据来源链接"工具用
    - competitors：每竞品的 rank 视图（current/delta_dod/delta_wow/history/app_id 等）
    """
    out = {
        "leaderboard": list(D.get("leaderboard") or []),
        "baseline": dict(D.get("baseline") or {}),
        "registry": dict(D.get("competitor_registry") or {}),
        "competitors": {},
    }
    for name, snap in (D.get("competitors") or {}).items():
        r = snap.get("rank") or {}
        out["competitors"][name] = {
            "current": r.get("current"),
            "delta_dod": r.get("delta_dod"),
            "delta_wow": r.get("delta_wow"),
            "history": dict(r.get("history") or {}),
            "fast_mover": bool(r.get("fast_mover")),
            "is_new_contender": bool(r.get("is_new_contender")),
            "app_id": r.get("app_id") or snap.get("ios_id"),
            "ios_id": snap.get("ios_id"),
            "android_id": snap.get("android_id"),
            "color": snap.get("color"),
        }
    return out


def _adapt_competitor_details(D):
    out = {}
    for name, snap in D["competitors"].items():
        deep = snap["comments"].get("deep_analysis")
        kw = snap["comments"].get("feature_keywords") or {}
        if not (deep or kw):
            continue
        regions = {}
        for code, r in (snap["comments"].get("by_region") or {}).items():
            regions[code] = {
                "label": r.get("label", code),
                "total": r["count"],
                "labels": dict(r.get("labels") or {}),
                "reviews": list(r.get("reviews") or []),
                "gp_count": 0,
                "ios_count": 0,
            }
        out[name] = {
            "competitor": name,
            "generated_at": D["meta"].get("generated_at"),
            "days_analyzed": 7,
            "total_reviews": snap["comments"]["total"],
            "regions": regions,
            "feature_analysis": {
                "summary": deep or "",
                "feature_keywords": dict(kw),
                "total_reviews": snap["comments"]["total"],
                "label_distribution": dict(snap["comments"].get("labels") or {}),
                "platform_distribution": {},
                "region_distribution": {},
                "feature_review_count": snap["comments"]["total"],
            },
        }
    return out


# ---- 触发聚合 + 派生全局视图 ---------------------------------------------

_dashboard_data = _ensure_dashboard_data()

strategy_data = _adapt_strategy(_dashboard_data)
market_data = _adapt_market(_dashboard_data)
comment_data = _adapt_comments(_dashboard_data)
ranking_history = _adapt_ranking_history(_dashboard_data)
competitor_registry = _dashboard_data.get("competitor_registry") or {}
competitor_details = _adapt_competitor_details(_dashboard_data)
weekly_review_data = _dashboard_data.get("weekly", {}).get("comment") or {}
commercial_data = _adapt_commercial(_dashboard_data)
commercial_weekly_data = _dashboard_data.get("weekly", {}).get("commercial") or {}
community_data = _adapt_community(_dashboard_data)
rank_data = _adapt_rank_view(_dashboard_data)
product_updates = _adapt_product_updates(_dashboard_data)
reviews_analysis = _adapt_reviews_analysis(_dashboard_data)

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def date_str():
    return datetime.now().strftime("%Y年%m月%d日")

# 竞品颜色映射
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

# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------

def compute_metrics():
    changes_detected = strategy_data.get("changes_detected", 0) if strategy_data else 0

    max_rank_delta = 0
    max_rank_comp = ""
    if market_data:
        perf = market_data.get("competitor_performance", {})
        for comp_name, info in perf.items():
            delta = info.get("delta")
            if delta is not None and abs(delta) > abs(max_rank_delta):
                max_rank_delta = delta
                max_rank_comp = comp_name

    total_negative = 0
    if comment_data:
        for comp_info in comment_data.get("competitors", {}).values():
            for region_data in comp_info.get("regions", {}).values():
                total_negative += region_data.get("negative_count", region_data.get("count", 0))

    monitored = strategy_data.get("total_monitored", 0) if strategy_data else 0

    return {
        "changes_detected": changes_detected,
        "max_rank_delta": max_rank_delta,
        "max_rank_comp": max_rank_comp,
        "total_negative": total_negative,
        "monitored": monitored,
    }

metrics = compute_metrics()

# ---------------------------------------------------------------------------
# 构建竞品列表（侧边栏）
# ---------------------------------------------------------------------------

def build_competitor_list():
    items = []
    colors = ["#7b6ef6", "#4ecca3", "#f5a623", "#ff5c5c", "#60a5fa", "#a78bfa", "#f472b6", "#34d399"]
    names = []
    if strategy_data:
        names = list(strategy_data.get("competitors", {}).keys())
    elif market_data:
        names = list(market_data.get("competitor_performance", {}).keys())
    for i, name in enumerate(names[:8]):
        c = colors[i % len(colors)]
        # 点击竞品跳转到竞品详情页
        items.append(f'<div class="nav-item" onclick="showCompetitorDetail(\'{name}\')"><div class="nav-dot" style="background:{c}"></div> {name}</div>')
    return "\n".join(items) if items else '<div class="nav-item" style="color:var(--muted);font-size:12px">暂无竞品数据</div>'

# ---------------------------------------------------------------------------
# 预警（v2 — 全部由 data_pipeline.alert_engine 产出）
#
# 旧版本曾在本文件 build_alerts() 内重复实现 4 条规则；v2 后台聚合层已统一
# 通过 alert_engine 生成 dashboard_data.alerts，本文件直接消费。
# 保留 build_alerts() 函数名只为减少调用方迁移成本，行为是一致读 JSON。
# ---------------------------------------------------------------------------


def build_alerts():
    """读 dashboard_data.alerts（来自 alert_engine）并以 dict 形式返回。"""
    return list(_dashboard_data.get("alerts") or [])


def _legacy_build_alerts_disabled():
    """旧 build_alerts 实现已禁用（保留以备回滚参考），不再执行。"""
    """根据三条预警规则生成预警列表"""
    alerts = []

    # ---- 规则1: 竞品出现低星评论 ----
    if comment_data:
        for comp_name, comp_info in comment_data.get("competitors", {}).items():
            total_comments = sum(r.get("count", 0) for r in comp_info.get("regions", {}).values())
            total_negative = sum(r.get("negative_count", r.get("count", 0)) for r in comp_info.get("regions", {}).values())
            if total_negative > 0:
                label_counter = Counter()
                for region_data in comp_info.get("regions", {}).values():
                    for label, count in region_data.get("labels", {}).items():
                        if count > 0:
                            label_counter[label] += count
                top_labels = "、".join(f"{label}({count}条)" for label, count in label_counter.most_common(3))
                label_str = top_labels if top_labels else "暂无标签分布"
                alerts.append({
                    "type": "negative_review",
                    "severity": "danger",
                    "severity_label": "高威胁",
                    "icon": "",
                    "title": f"{comp_name} 出现低星评论",
                    "desc": f"近3天检测到 {total_negative} 条低星评论，共抓取 {total_comments} 条评论。高频信号：{label_str}。",
                    "time": "今天",
                    "competitor": comp_name,
                })

    # ---- 规则2: 体育榜上app在一周内排名上升>10位 ----
    # 检查 ranking_history 是否有足够的历史数据做周对比
    dates = sorted(ranking_history.keys())
    if len(dates) >= 2:
        latest_date = dates[-1]
        # 找一周前的日期
        from datetime import datetime, timedelta
        latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
        week_ago_dt = latest_dt - timedelta(days=7)
        week_ago_str = week_ago_dt.strftime("%Y-%m-%d")

        # 找最接近一周前的日期
        week_ago_date = None
        for d in dates:
            if d <= week_ago_str:
                week_ago_date = d
            else:
                break
        if week_ago_date is None and len(dates) > 1:
            week_ago_date = dates[0]

        if week_ago_date and week_ago_date != latest_date:
            latest_ranks = ranking_history[latest_date]
            week_ago_ranks = ranking_history[week_ago_date]

            # 构建 app_id -> name 映射
            id_to_name = {}
            if market_data:
                for comp_name, info in market_data.get("competitor_performance", {}).items():
                    aid = info.get("app_id")
                    if aid:
                        id_to_name[aid] = comp_name
            for name, app in competitor_registry.items():
                aid = app.get("app_id") or app.get("ios")
                if aid and name:
                    id_to_name[str(aid)] = name
            # 从 leaderboard 也获取名称
            for item in market_data.get("leaderboard", []):
                aid = item.get("app_id")
                name = item.get("name")
                if aid and name and aid not in id_to_name:
                    id_to_name[aid] = name

            for app_id, current_rank in latest_ranks.items():
                if app_id in week_ago_ranks:
                    old_rank = week_ago_ranks[app_id]
                    delta = old_rank - current_rank  # 正数 = 排名上升
                    if delta > 10:
                        app_name = id_to_name.get(app_id, f"App(ID:{app_id})")
                        alerts.append({
                            "type": "rank_rise",
                            "severity": "warn",
                            "severity_label": "中威胁",
                            "icon": "",
                            "title": f"{app_name} 排名快速上升 {delta} 位",
                            "desc": f"一周内从 #{old_rank} 上升至 #{current_rank}，上升 {delta} 位，买量或功能更新信号明显。",
                            "time": "本周",
                            "competitor": app_name,
                        })

    # ---- 规则3: 竞品app进行版本迭代，涉及功能内容，需要检查 ----
    if strategy_data:
        for comp_name, comp_info in strategy_data.get("competitors", {}).items():
            if "error" in comp_info:
                continue
            if comp_info.get("has_changed") or comp_info.get("version_changed"):
                version = comp_info.get("version", "未知")
                release_notes = comp_info.get("release_notes", "")
                changes = comp_info.get("changes", [])
                # 判断是否涉及功能内容
                feature_keywords = ["功能", "feature", "new", "更新", "上线", "新增", "redesign", "redesigned",
                                    "widget", "widgets", "multiview", "lineup", "depth chart", "insight",
                                    "AI", "ai", "智能", "分析", "统计", "stat", "数据"]
                has_feature_content = False
                if changes:
                    has_feature_content = True
                elif release_notes:
                    notes_lower = release_notes.lower()
                    for kw in feature_keywords:
                        if kw.lower() in notes_lower:
                            has_feature_content = True
                            break

                if has_feature_content:
                    # 提取关键变化摘要
                    change_summary = ""
                    if changes:
                        change_summary = "；".join(changes[:3])
                    elif release_notes:
                        # 取前100字
                        change_summary = release_notes[:100].replace("\n", " ").strip() + "..."

                    alerts.append({
                        "type": "version_update",
                        "severity": "danger",
                        "severity_label": "高威胁 · 建议评估",
                        "icon": "",
                        "title": f"{comp_name} 版本更新至 v{version}，涉及功能变更",
                        "desc": change_summary if change_summary else f"版本 {version} 有更新内容，建议立即评估差异化策略。",
                        "time": "今天",
                        "competitor": comp_name,
                        "version": version,
                    })

    # ---- 规则4: 竞品商业策略变动 ----
    if commercial_data:
        for comp_name, comp_info in commercial_data.get("competitors", {}).items():
            # 价格变动预警
            for pa in comp_info.get("price_alerts", []):
                alerts.append({
                    "type": "commercial_change",
                    "severity": "danger",
                    "severity_label": "高威胁",
                    "icon": "",
                    "title": f"{comp_name} IAP {pa.get('direction','变动')}: {pa.get('name','')}",
                    "desc": f"价格从 ${pa.get('prev',0)} 变为 ${pa.get('curr',0)}（{pa.get('direction','')} ${abs(pa.get('delta',0))}）",
                    "time": "今天",
                    "competitor": comp_name,
                })
            # IAP 新增/移除预警
            for ic in comp_info.get("iap_changes", []):
                alerts.append({
                    "type": "commercial_change",
                    "severity": "warn",
                    "severity_label": "中威胁",
                    "icon": "",
                    "title": f"{comp_name} IAP {ic.get('type','变动')}: {ic.get('name','')}",
                    "desc": f"检测到内购项「{ic.get('name','')}」{ic.get('type','变动')}，建议关注竞品商业策略调整。",
                    "time": "今天",
                    "competitor": comp_name,
                })
            # 博彩导流信号
            if comp_info.get("betting_signals"):
                alerts.append({
                    "type": "commercial_change",
                    "severity": "warn",
                    "severity_label": "中威胁",
                    "icon": "",
                    "title": f"{comp_name} 检测到博彩导流信号",
                    "desc": f"应用描述中包含博彩相关关键词: {', '.join(comp_info.get('description_keywords', []))}",
                    "time": "今天",
                    "competitor": comp_name,
                })

    # 按严重程度排序：danger > warn > info
    severity_order = {"danger": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 99))

    return alerts


def build_alert_strip_html(alerts):
    """构建总览页面的预警条"""
    if not alerts:
        return """
        <div class="alert-strip" style="background:rgba(78,204,163,0.08);border-color:rgba(78,204,163,0.2)" onclick="showPage('alerts')">
          <span class="alert-icon"></span>
          <span class="alert-text" style="color:var(--accent2)">当前无预警，所有竞品状态正常</span>
          <span class="alert-count" style="background:rgba(78,204,163,0.15);color:var(--accent2)">查看全部 →</span>
        </div>
        """

    # 取最高严重级别的预警作为展示
    top_alert = alerts[0]
    severity_colors = {"danger": "var(--danger)", "warn": "var(--warn)", "info": "var(--accent)"}
    border_colors = {"danger": "rgba(255,92,92,0.2)", "info": "rgba(123,110,246,0.2)"}
    bg_colors = {"danger": "rgba(255,92,92,0.08)", "warn": "rgba(245,166,35,0.08)", "info": "rgba(123,110,246,0.08)"}
    sev = top_alert.get("severity", "warn")

    return f"""
    <div class="alert-strip" style="background:{bg_colors.get(sev, 'rgba(245,166,35,0.08)')};border-color:{border_colors.get(sev, 'rgba(245,166,35,0.2)')}" onclick="showPage('alerts')">
      <span class="alert-icon">{top_alert.get('icon', '')}</span>
      <span class="alert-text" style="color:{severity_colors.get(sev, 'var(--warn)')}"><strong>{top_alert['title']}</strong>：{top_alert['desc'][:60]}{'...' if len(top_alert['desc']) > 60 else ''}</span>
      <span class="alert-count" style="background:{bg_colors.get(sev, 'rgba(245,166,35,0.15)')};color:{severity_colors.get(sev, 'var(--warn)')}">共 {len(alerts)} 条预警 →</span>
    </div>
    """


def build_alert_page_html(alerts):
    """v2: page-alerts 改为 JS 渲染，本函数返回空（保留接口兼容）。"""
    return ""


def build_alerts_data_json(alerts):
    """把 alerts 列表序列化为 JS 字面量（注入到 ALERTS_DATA_PLACEHOLDER）。

    每条 alert 必含字段：type / severity / severity_label / title / desc / time /
    competitor / payload，与 schema.Alert.to_dict 完全一致。
    """
    return json.dumps(list(alerts or []), ensure_ascii=False)


def _legacy_alert_page_disabled(alerts):
    """旧 page-alerts HTML 渲染（保留参考）。"""

    severity_config = {
        "danger": {"border": "var(--danger)", "label": "高威胁", "cls": "ft-feature"},
        "warn": {"border": "var(--warn)", "label": "中威胁", "cls": "ft-price"},
        "info": {"border": "var(--accent2)", "label": "信息", "cls": "ft-bug"},
    }

    html = '<div class="card full-card">'
    for alert in alerts:
        cfg = severity_config.get(alert.get("severity", "info"), severity_config["info"])
        comp_color = COMP_COLORS.get(alert.get("competitor", ""), "var(--accent)")
        html += f"""
        <div class="feed-item" style="border-left:3px solid {cfg['border']}">
          <div class="feed-meta">
            <span class="feed-source" style="color:{comp_color}">{alert.get('competitor', '竞品')}</span>
            <span class="feed-type {cfg['cls']}">{cfg['label']}</span>
          </div>
          <div class="feed-title">{alert.get('icon', '•')} {alert['title']}</div>
          <div class="feed-desc">{alert['desc']}</div>
          <div class="feed-time">{alert.get('time', '最近')}</div>
        </div>
        """
    html += '</div>'
    return html


# ---------------------------------------------------------------------------
# 构建 Feed 流
# ---------------------------------------------------------------------------

def build_feed_html():
    feed_items = []

    if strategy_data:
        for comp_name, comp_info in strategy_data.get("competitors", {}).items():
            if "error" in comp_info:
                continue
            if comp_info.get("has_changed"):
                for change in comp_info.get("changes", []):
                    feed_items.append({
                        "competitor": comp_name,
                        "text": change,
                        "version": comp_info.get("version", ""),
                        "type": "feature",
                        "time": "今天",
                    })
            elif comp_info.get("is_first_record"):
                feed_items.append({
                    "competitor": comp_name,
                    "text": f"首次记录 · 版本 {comp_info.get('version', '未知')}",
                    "version": comp_info.get("version", ""),
                    "type": "update",
                    "time": "今天",
                })

    if comment_data:
        for comp_name, comp_info in comment_data.get("competitors", {}).items():
            total = sum(r.get("count", 0) for r in comp_info.get("regions", {}).values())
            negative = sum(r.get("negative_count", r.get("count", 0)) for r in comp_info.get("regions", {}).values())
            if total > 0:
                feed_items.append({
                    "competitor": comp_name,
                    "text": f"新增 {total} 条用户评论，其中 {negative} 条为低星评论",
                    "version": "",
                    "type": "bug",
                    "time": "今天",
                })

    if not feed_items:
        return '<div style="padding:20px;color:var(--muted);font-size:13px">暂无最新动态</div>'

    type_config = {
        "feature": {"label": "新功能", "cls": "ft-feature", "signal": "高威胁 · 建议评估", "signal_color": "var(--danger)"},
        "bug": {"label": "用户反馈", "cls": "ft-bug", "signal": "机会 · 可承接", "signal_color": "var(--accent2)"},
        "rank": {"label": "排名", "cls": "ft-price", "signal": "中威胁 · 持续观察", "signal_color": "var(--warn)"},
        "update": {"label": "更新", "cls": "ft-feature", "signal": "信息 · 已记录", "signal_color": "var(--muted)"},
    }

    html = ""
    for item in feed_items[:6]:
        cfg = type_config.get(item["type"], type_config["update"])
        comp_color = COMP_COLORS.get(item["competitor"], "var(--accent)")
        html += f"""
        <div class="feed-item" onclick="openModal('feature')">
          <div class="feed-meta">
            <span class="feed-source" style="color:{comp_color}">{item['competitor']}</span>
            <span class="feed-type {cfg['cls']}">{cfg['label']}</span>
          </div>
          <div class="feed-title">{item['text']}</div>
          <div class="feed-desc">版本 {item['version'] if item['version'] else 'N/A'}</div>
          <div class="feed-time">{item['time']}</div>
          <div class="feed-signal">
            <div class="signal-dot" style="background:{cfg['signal_color']}"></div>
            <span style="color:{cfg['signal_color']};font-size:11px;font-family:var(--mono)">{cfg['signal']}</span>
          </div>
        </div>
        """
    return html

# ---------------------------------------------------------------------------
# 构建需求词云
# ---------------------------------------------------------------------------

def build_keyword_cloud():
    keyword_counter = Counter()
    if comment_data:
        for comp_info in comment_data.get("competitors", {}).values():
            for region_data in comp_info.get("regions", {}).values():
                for review in region_data.get("reviews", []):
                    content = review.get("content", "")
                    label = review.get("label", "")
                    if "高价值功能请求" in label or "问题抱怨" in label or "request" in label.lower():
                        words = content.lower().split()
                        stop_words = {"the", "this", "that", "with", "from", "have", "been", "was", "were", "what", "when", "where", "there", "their", "about", "would", "could", "should", "after", "still", "more", "some", "than", "also", "other", "into", "only", "over", "such", "very", "just", "because", "example", "but", "not", "they", "them", "its", "has", "had", "can", "will", "may", "all", "are", "for", "you", "your", "our"}
                        for w in words:
                            w = w.strip(".,!?\"';:()[]{}")
                            if len(w) > 3 and w not in stop_words:
                                keyword_counter[w] += 1

    if not keyword_counter:
        keyword_counter = Counter({
            "offline": 28, "export": 22, "dark": 18, "multi-account": 15,
            "api": 12, "batch": 10, "collaboration": 8, "report": 7,
            "notification": 6, "sync": 5, "widget": 4, "customize": 3,
        })

    top_keywords = keyword_counter.most_common(15)
    sizes = [kw[1] for kw in top_keywords]
    max_size = max(sizes) if sizes else 1
    min_size = min(sizes) if sizes else 1

    html = '<div style="padding:16px 20px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">'
    colors = ["var(--text)", "var(--muted)", "var(--accent2)", "var(--warn)", "var(--accent)", "var(--danger)"]
    for i, (word, count) in enumerate(top_keywords):
        font_size = 11 + (count - min_size) / max(1, max_size - min_size) * 16
        color = colors[i % len(colors)]
        html += f'<span style="font-size:{font_size:.0f}px;font-weight:{600 if count == max_size else 400};color:{color};font-family:var(--display)">{word}</span>\n'
    html += '</div>'
    html += f'<div style="padding:0 20px 16px;font-size:11px;color:var(--muted);font-family:var(--mono)">字号越大 = 提及越多 · 共 {sum(kw[1] for kw in top_keywords)} 次有效提及</div>'
    return html

# ---------------------------------------------------------------------------
# 构建排名趋势 SVG
# ---------------------------------------------------------------------------

def build_rank_trend_svg():
    dates = sorted(ranking_history.keys())
    if len(dates) < 2:
        return '<div style="padding:20px;color:var(--muted);font-size:13px">暂无历史排名数据，需多次采集后生成趋势图</div>'

    known_ids = {}
    if market_data:
        for comp_name, info in market_data.get("competitor_performance", {}).items():
            aid = info.get("app_id")
            if aid:
                known_ids[aid] = comp_name
    for name, app in competitor_registry.items():
        aid = app.get("app_id") or app.get("ios")
        if aid and name:
            known_ids[str(aid)] = name

    trends = {}
    for date in dates:
        day_data = ranking_history[date]
        for app_id, rank in day_data.items():
            if app_id in known_ids:
                name = known_ids[app_id]
                if name not in trends:
                    trends[name] = {}
                trends[name][date] = rank

    if not trends:
        return '<div style="padding:20px;color:var(--muted);font-size:13px">暂无已知竞品的排名历史数据</div>'

    colors = ["#7b6ef6", "#4ecca3", "#f5a623", "#ff5c5c", "#60a5fa", "#a78bfa"]
    color_idx = 0

    svg_w = 640
    svg_h = 140
    pad_l, pad_r, pad_t, pad_b = 35, 15, 20, 25
    plot_w = svg_w - pad_l - pad_r
    plot_h = svg_h - pad_t - pad_b

    all_ranks = [r for data in trends.values() for r in data.values()]
    if not all_ranks:
        return ""
    max_rank = max(all_ranks) + 5
    min_rank = max(1, min(all_ranks) - 5)

    date_list = sorted(set(d for data in trends.values() for d in data))
    if len(date_list) < 2:
        return ""

    def x_pos(idx):
        return pad_l + (idx / (len(date_list) - 1)) * plot_w

    def y_pos(rank):
        return pad_t + ((rank - min_rank) / (max_rank - min_rank)) * plot_h

    grid_lines = ""
    grid_labels = ""
    step = max(1, (max_rank - min_rank) // 4)
    for r in range(min_rank, max_rank + 1, step):
        y = y_pos(r)
        grid_lines += f'<line x1="{pad_l}" y1="{y:.1f}" x2="{svg_w - pad_r}" y2="{y:.1f}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>\n'
        grid_labels += f'<text x="{pad_l - 5}" y="{y + 3:.1f}" fill="rgba(255,255,255,0.2)" font-size="9" font-family="monospace" text-anchor="end">#{r}</text>\n'

    paths = ""
    legend_items = ""
    for name, data in trends.items():
        sorted_dates = sorted(data.keys())
        points = []
        for d in sorted_dates:
            if d in data and d in date_list:
                idx = date_list.index(d)
                points.append(f"{x_pos(idx):.1f},{y_pos(data[d]):.1f}")
        if len(points) >= 2:
            path_d = "M" + " L".join(points)
            color = colors[color_idx % len(colors)]
            paths += f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round"/>\n'
            legend_items += f'<span style="font-size:11px;font-family:var(--mono);color:{color}">● {name}</span>\n'
            color_idx += 1

    date_labels = ""
    step_date = max(1, len(date_list) // 5)
    for i in range(0, len(date_list), step_date):
        d = date_list[i]
        label = d[5:]
        date_labels += f'<text x="{x_pos(i):.1f}" y="{svg_h - 5}" fill="rgba(255,255,255,0.3)" font-size="9" font-family="monospace" text-anchor="middle">{label}</text>\n'

    return f"""
    <div style="padding:8px 20px 4px;display:flex;gap:20px;flex-wrap:wrap">
      {legend_items}
    </div>
    <div style="padding:0 20px 20px">
      <svg viewBox="0 0 {svg_w} {svg_h}" style="width:100%;height:{svg_h}px">
        {grid_lines}
        {grid_labels}
        {paths}
        {date_labels}
      </svg>
    </div>
    """

# ---------------------------------------------------------------------------
# 多源数据 (multi_source from market_rank.json)
# ---------------------------------------------------------------------------

multi_source = market_data.get("multi_source", {}) if market_data else {}
baseline_app = market_data.get("baseline_app", "AllFootball") if market_data else "AllFootball"
baseline_label = market_data.get("baseline_label", "All Football") if market_data else "All Football"
baseline_comparison = market_data.get("baseline_comparison", {}) if market_data else {}


def _fmt_downloads(val):
    if val is None:
        return "—"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.0f}K"
    return str(val)


def _fmt_revenue(val):
    if val is None:
        return "—"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:.0f}"


def _fmt_sentiment(val):
    if val is None:
        return "—"
    if val > 0.3:
        return f'<span style="color:var(--accent2)">{val:+.2f}</span>'
    if val < -0.1:
        return f'<span style="color:var(--danger)">{val:+.2f}</span>'
    return f'<span style="color:var(--muted)">{val:+.2f}</span>'


def _fmt_rating_growth(val):
    if val is None:
        return "—"
    if val > 0:
        return f'<span style="color:var(--accent2)">+{val:.2%}</span>'
    if val < 0:
        return f'<span style="color:var(--danger)">{val:.2%}</span>'
    return f'<span style="color:var(--muted)">0%</span>'


def _metric_value(ms: dict, metric: str):
    return (ms.get("metrics") or {}).get(metric)


def _fmt_metric_value(metric: str, val):
    if val is None:
        return "—"
    if metric == "rank":
        return f"#{int(val)}"
    if metric in {"downloads", "rating_count", "review_count"}:
        return _fmt_downloads(val)
    if metric == "revenue_proxy":
        return _fmt_revenue(val)
    if metric == "rating_growth":
        return f"{val:+.2%}"
    if metric == "sentiment_score":
        return f"{val:+.2f}"
    if metric == "update_frequency":
        return f"{val:.0f}d"
    return str(val)


def _fmt_delta(metric: str, val):
    if val is None:
        return "—"
    if metric == "rank":
        return f"{val:+.0f}"
    if metric in {"downloads", "rating_count", "review_count"}:
        sign = "+" if val > 0 else "-"
        return f"{sign}{_fmt_downloads(abs(val))}" if val != 0 else "0"
    if metric == "revenue_proxy":
        sign = "+" if val > 0 else "-"
        return f"{sign}{_fmt_revenue(abs(val))}" if val != 0 else "$0"
    if metric == "rating_growth":
        return f"{val:+.2%}"
    if metric == "sentiment_score":
        return f"{val:+.2f}"
    if metric == "update_frequency":
        return f"{val:+.0f}d"
    return f"{val:+.2f}"


def _fmt_multiple(val):
    if val is None:
        return "—"
    return f"{val:.1f}x"


def _status_for_metric(metric: str, ratio):
    if metric == "update_frequency":
        return ("观察", "var(--muted)")
    if ratio is None:
        return ("样本不足", "var(--muted)")
    if ratio > 1:
        return ("领先", "var(--accent2)")
    if ratio < 1:
        return ("落后", "var(--danger)")
    return ("持平", "var(--muted)")


# ---------------------------------------------------------------------------
# 构建排名表格 (含多源数据列)
# ---------------------------------------------------------------------------

def build_rank_table():
    leaderboard = market_data.get("leaderboard", []) if market_data else []
    if not leaderboard:
        return '<div style="padding:20px;color:var(--muted);font-size:13px">暂无排名数据</div>'

    rows = ""
    for item in leaderboard[:20]:
        rank = item.get("rank", "?")
        name = item.get("name", "Unknown")
        delta = item.get("delta")
        is_known = item.get("is_known", False)

        if delta is not None:
            if delta > 0:
                delta_str = f'<span class="rank-change up">↑ +{delta}</span>'
                bar_color = "var(--accent2)"
            elif delta < 0:
                delta_str = f'<span class="rank-change down">↓ {delta}</span>'
                bar_color = "var(--danger)"
            else:
                delta_str = f'<span class="rank-change neutral">→ 0</span>'
                bar_color = "var(--accent)"
        else:
            delta_str = f'<span class="rank-change neutral">—</span>'
            bar_color = "var(--border2)"

        tag = '<span class="rank-tag self">已知</span>' if is_known else ""
        bar_width = max(10, 100 - rank)

        # 多源数据列
        ms = None
        for comp_name, ms_data in multi_source.items():
            if comp_name.lower() in name.lower() or name.lower() in comp_name.lower():
                ms = ms_data
                break

        dl_str = _fmt_downloads(_metric_value(ms, "downloads")) if ms else "—"
        sent_str = _fmt_sentiment(_metric_value(ms, "sentiment_score")) if ms else "—"
        rg_str = _fmt_rating_growth(_metric_value(ms, "rating_growth")) if ms else "—"

        rows += f"""
        <div class="rank-row" onclick="openModal('rank')">
          <div class="rank-num">{rank}</div>
          <div class="rank-name">{name} {tag}</div>
          <div class="rank-score">#{rank}</div>
          {delta_str}
          <div class="rank-extra">{dl_str}</div>
          <div class="rank-extra">{rg_str}</div>
          <div class="rank-extra">{sent_str}</div>
          <div class="rank-bar-wrap"><div class="rank-bar"><div class="rank-bar-fill" style="width:{bar_width}%;background:{bar_color}"></div></div></div>
        </div>
        """
    return rows


# ---------------------------------------------------------------------------
# 构建多源竞品排名卡片 (排名页底部)
# ---------------------------------------------------------------------------

def build_multi_source_rank_section():
    if not multi_source:
        return ""
    cards = ""
    for comp_name, ms in multi_source.items():
        color = COMP_COLORS.get(comp_name, "var(--accent)")
        raw = ms.get("_raw", {})
        ar = raw.get("androidrank", {})
        st_data = raw.get("sensor_tower", {})
        reddit = raw.get("reddit", {})

        # Androidrank block
        ar_dl = ar.get("estimated_downloads")
        ar_rating = ar.get("current_rating")
        ar_total = ar.get("total_ratings")
        ar_html = f"""
          <div style="margin-bottom:8px">
            <div style="font-size:10px;color:var(--muted);font-family:var(--mono);margin-bottom:4px">ANDROIDRANK</div>
            <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px">
              <span>下载量 <b style="color:var(--accent)">{_fmt_downloads(ar_dl)}</b></span>
              <span>评分 <b>{f"{ar_rating:.2f}" if ar_rating else "—"}</b></span>
              <span>总评数 <b>{_fmt_downloads(ar_total) if ar_total else "—"}</b></span>
            </div>
          </div>"""

        # Sensor Tower block
        st_rank_free = st_data.get("category_rank_free")
        st_rank_gross = st_data.get("category_rank_grossing")
        st_rev = st_data.get("monthly_revenue_usd")
        st_dl = st_data.get("monthly_downloads")
        st_countries = ", ".join(st_data.get("top_countries", [])[:5]) or "—"
        rb = st_data.get("rating_breakdown", {})
        rb_html = ""
        if rb:
            total_r = sum(rb.values()) or 1
            rb_html = " · ".join(f"{k}: {v/total_r:.0%}" for k, v in rb.items())
        st_html = f"""
          <div style="margin-bottom:8px">
            <div style="font-size:10px;color:var(--muted);font-family:var(--mono);margin-bottom:4px">SENSOR TOWER</div>
            <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px">
              <span>免费榜 <b style="color:var(--accent)">{"#"+str(st_rank_free) if st_rank_free else "—"}</b></span>
              <span>畅销榜 <b>{"#"+str(st_rank_gross) if st_rank_gross else "—"}</b></span>
              <span>月收入 <b style="color:var(--accent2)">{_fmt_revenue(st_rev)}</b></span>
              <span>月下载 <b>{_fmt_downloads(st_dl)}</b></span>
            </div>
            <div style="font-size:11px;color:var(--muted);margin-top:4px">主要市场: {st_countries}</div>
            {f'<div style="font-size:10px;color:var(--muted);margin-top:2px">评分分布: {rb_html}</div>' if rb_html else ""}
          </div>"""

        # Reddit block
        posts = reddit.get("posts", [])
        sent = _metric_value(ms, "sentiment_score")
        sent_str = _fmt_sentiment(sent)
        posts_html = ""
        for p in posts[:5]:
            ratio = p.get("upvote_ratio", 0.5)
            ratio_color = "var(--accent2)" if ratio >= 0.7 else ("var(--danger)" if ratio < 0.4 else "var(--muted)")
            posts_html += f"""<div style="padding:4px 0;border-bottom:1px solid var(--border);font-size:11px">
              <span style="color:var(--muted)">r/{p.get("subreddit","?")} · ↑{p.get("score",0)} · <span style="color:{ratio_color}">{ratio:.0%}</span></span>
              <div style="color:var(--text);margin-top:2px">{p.get("title","")}</div>
            </div>"""
        reddit_html = f"""
          <div>
            <div style="font-size:10px;color:var(--muted);font-family:var(--mono);margin-bottom:4px">REDDIT ({reddit.get("mention_count",0)} 条) · 情绪 {sent_str}</div>
            {posts_html if posts_html else '<div style="font-size:11px;color:var(--muted)">暂无帖子</div>'}
          </div>"""

        cards += f"""
        <div style="padding:16px 20px;border-bottom:1px solid var(--border)">
          <div style="font-weight:700;color:{color};font-size:14px;margin-bottom:12px">{comp_name}</div>
          {ar_html}{st_html}{reddit_html}
        </div>"""

    return f"""
    <div class="card full-card" style="margin-top:16px">
      <div class="card-head"><div class="card-title">竞品多源详细数据</div><div class="card-action">Androidrank · Sensor Tower · Reddit</div></div>
      {cards}
    </div>"""


# ---------------------------------------------------------------------------
# 构建多源收入数据 (商业分析页)
# ---------------------------------------------------------------------------

def build_multi_source_revenue_section():
    if not multi_source:
        return ""
    rows = ""
    for comp_name, ms in multi_source.items():
        color = COMP_COLORS.get(comp_name, "var(--accent)")
        rev_str = _fmt_revenue(_metric_value(ms, "revenue_proxy"))
        dl_str = _fmt_downloads(_metric_value(ms, "downloads"))
        rank_val = _metric_value(ms, "rank")
        rank_str = f"#{rank_val}" if rank_val else "—"

        raw = ms.get("_raw", {})
        st = raw.get("sensor_tower", {})
        countries = ", ".join(st.get("top_countries", [])[:3]) if st.get("top_countries") else "—"

        rpd = 0
        revenue_proxy = _metric_value(ms, "revenue_proxy")
        download_proxy = _metric_value(ms, "downloads")
        if revenue_proxy and download_proxy and download_proxy > 0:
            rpd = revenue_proxy / download_proxy * 1000
        rpd_str = f"${rpd:.2f}" if rpd > 0 else "—"

        rows += f"""
        <div style="display:grid;grid-template-columns:130px 90px 100px 80px 80px 100px;align-items:center;padding:10px 20px;border-bottom:1px solid var(--border);font-size:13px">
          <span style="font-weight:600;color:{color}">{comp_name}</span>
          <span style="color:var(--accent2)">{rev_str}</span>
          <span>{dl_str}</span>
          <span>{rank_str}</span>
          <span>{rpd_str}</span>
          <span style="color:var(--muted);font-size:11px">{countries}</span>
        </div>"""

    return f"""
    <div class="card full-card" style="margin-top:16px">
      <div class="card-head"><div class="card-title">竞品收入概览</div><div class="card-action">Sensor Tower · 月度数据</div></div>
      <div style="display:grid;grid-template-columns:130px 90px 100px 80px 80px 100px;padding:8px 20px;font-size:10px;font-family:var(--mono);color:var(--muted);border-bottom:1px solid var(--border)">
        <span>竞品</span><span>月收入</span><span>月下载</span><span>分类排名</span><span>RPD</span><span>主要市场</span>
      </div>
      {rows}
    </div>"""


def build_multi_source_json():
    """将多源数据注入到 COMMERCIAL_DATA 中供 AI 报告使用"""
    if not multi_source:
        return {}
    return {name: {
        "revenue_proxy": _metric_value(d, "revenue_proxy"),
        "download_proxy": _metric_value(d, "downloads"),
        "rank": _metric_value(d, "rank"),
        "sentiment_score": _metric_value(d, "sentiment_score"),
        "rating_growth": _metric_value(d, "rating_growth"),
    } for name, d in multi_source.items()}


def build_baseline_comparison_section():
    if not baseline_comparison:
        return ""

    metric_labels = {
        "rank": "Rank",
        "downloads": "Downloads",
        "rating_count": "Rating Count",
        "rating_growth": "Rating Growth",
        "review_count": "Review Count",
        "sentiment_score": "Sentiment",
        "update_frequency": "Update Frequency",
        "revenue_proxy": "Revenue Proxy",
    }

    header = f"""
    <div class="card full-card" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">相对 {baseline_label} 表现</div>
        <div class="card-action">Current · Baseline · Delta · Multiple</div>
      </div>
      <div style="display:grid;grid-template-columns:130px 120px 110px 110px 100px 90px 70px;padding:8px 20px;font-size:10px;font-family:var(--mono);color:var(--muted);border-bottom:1px solid var(--border)">
        <span>App</span><span>Metric</span><span>Current</span><span>{baseline_label}</span><span>Delta</span><span>Multiple</span><span>Status</span>
      </div>
    """

    rows = ""
    for app_name, item in baseline_comparison.items():
        if app_name == baseline_app:
            continue
        color = COMP_COLORS.get(app_name, "var(--accent)")
        metrics = item.get("metrics", {})
        baseline = item.get("baseline", {})
        comparison = item.get("comparison", {})
        deltas = comparison.get("delta", {})
        ratios = comparison.get("ratio", {})
        for metric, metric_label in metric_labels.items():
            current_val = metrics.get(metric)
            baseline_val = baseline.get(metric)
            delta_val = deltas.get(metric)
            ratio_val = ratios.get(metric)
            status_text, status_color = _status_for_metric(metric, ratio_val)
            ratio_color = status_color if ratio_val is not None else "var(--muted)"
            rows += f"""
            <div style="display:grid;grid-template-columns:130px 120px 110px 110px 100px 90px 70px;align-items:center;padding:10px 20px;border-bottom:1px solid var(--border);font-size:12px">
              <span style="font-weight:600;color:{color}">{app_name}</span>
              <span style="color:var(--muted)">{metric_label}</span>
              <span>{_fmt_metric_value(metric, current_val)}</span>
              <span>{_fmt_metric_value(metric, baseline_val)}</span>
              <span>{_fmt_delta(metric, delta_val)}</span>
              <span style="color:{ratio_color};font-family:var(--mono)">{_fmt_multiple(ratio_val)}</span>
              <span style="color:{status_color}">{status_text}</span>
            </div>
            """

    return header + rows + "</div>"

# ---------------------------------------------------------------------------
# 构建产品动态页面
# ---------------------------------------------------------------------------

def build_product_page():
    if not strategy_data:
        return '<div style="padding:20px;color:var(--muted);font-size:13px">暂无产品动态数据</div>'

    html = ""
    competitors = strategy_data.get("competitors", {})
    for comp_name, comp_info in competitors.items():
        if "error" in comp_info:
            continue
        version = comp_info.get("version", "N/A")
        release_notes = comp_info.get("release_notes", "")
        has_changed = comp_info.get("has_changed", False)
        comp_color = COMP_COLORS.get(comp_name, "var(--accent)")

        desc = release_notes[:120] + "..." if len(release_notes) > 120 else (release_notes if release_notes else "暂无更新日志")

        html += f"""
        <div class="feed-item" onclick="openModal('feature')">
          <div class="feed-meta">
            <span class="feed-source" style="color:{comp_color}">{comp_name} · v{version}</span>
            <span class="feed-type ft-feature">{'有更新' if has_changed else '稳定'}</span>
          </div>
          <div class="feed-title">{comp_name} · 版本 {version}</div>
          <div class="feed-desc">{desc}</div>
          <div class="feed-time">最近更新</div>
        </div>
        """
    return html if html else '<div style="padding:20px;color:var(--muted);font-size:13px">暂无产品动态数据</div>'

# ---------------------------------------------------------------------------
# 构建评论页面
# ---------------------------------------------------------------------------

def build_review_page():
    if not comment_data:
        return '<div style="padding:20px;color:var(--muted);font-size:13px">暂无评论数据</div>'

    html = ""
    competitors = comment_data.get("competitors", {})
    for comp_name, comp_info in competitors.items():
        total = sum(r.get("count", 0) for r in comp_info.get("regions", {}).values())
        if total == 0:
            continue
        comp_color = COMP_COLORS.get(comp_name, "var(--accent)")

        reviews = []
        for region_code, region_data in comp_info.get("regions", {}).items():
            for review in region_data.get("reviews", []):
                reviews.append({
                    "region": region_code,
                    "score": review.get("score", 0),
                    "version": review.get("version", ""),
                    "label": review.get("label", ""),
                    "content": review.get("content", ""),
                })

        # 获取 AI 分析摘要
        summary = ""
        for region_code, region_data in comp_info.get("regions", {}).items():
            s = region_data.get("summary", "")
            if s:
                summary += f"\n\n--- {region_code.upper()} 区分析 ---\n\n{s}"

        html += f"""
        <div class="feed-item" onclick="openReviewModal('{comp_name}')">
          <div class="feed-meta">
            <span class="feed-source" style="color:{comp_color}">{comp_name}</span>
            <span class="feed-type ft-bug">{total} 条评论</span>
          </div>
          <div class="feed-title">{comp_name} · 共 {total} 条用户评论</div>
          <div class="feed-desc">
        """
        for r in reviews[:3]:
            content_short = r["content"][:80] + "..." if len(r["content"]) > 80 else r["content"]
            html += f'"{content_short}"<br>'
        html += f"""
          </div>
          <div class="feed-time" style="display:flex;align-items:center;gap:8px;margin-top:8px">
            <span>近3天</span>
            <button id="gen-btn-{comp_name}" class="btn" style="padding:4px 10px;font-size:11px" onclick="event.stopPropagation();generateAIAnalysis('{comp_name}')">生成 AI 分析</button>
          </div>
        </div>
        """
    return html if html else '<div style="padding:20px;color:var(--muted);font-size:13px">暂无评论数据</div>'


def build_review_data_json():
    """构建前端 REVIEW_DATA 所需的 JSON 数据"""
    if not comment_data:
        return "{}"
    result = {}
    competitors = comment_data.get("competitors", {})
    for comp_name, comp_info in competitors.items():
        total = sum(r.get("count", 0) for r in comp_info.get("regions", {}).values())
        if total == 0:
            continue
        reviews = []
        summary = ""
        for region_code, region_data in comp_info.get("regions", {}).items():
            for review in region_data.get("reviews", []):
                reviews.append({
                    "score": review.get("score", 0),
                    "version": review.get("version", "") or "",
                    "label": review.get("label", ""),
                    "content": review.get("content", ""),
                })
            s = region_data.get("summary", "")
            if s:
                summary += f"\n\n--- {region_code.upper()} 区分析 ---\n\n{s}"
        result[comp_name] = {
            "summary": summary.strip(),
            "reviews": reviews,
        }
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 构建竞品详情页数据 (JSON for frontend)
# ---------------------------------------------------------------------------

def build_competitor_detail_json():
    """构建前端 COMPETITOR_DETAIL_DATA 所需的 JSON 数据"""
    result = {}

    # 从 market_rank 获取排名信息
    rank_info = {}
    if market_data:
        for comp_name, info in market_data.get("competitor_performance", {}).items():
            rank_info[comp_name] = {
                "rank": info.get("rank"),
                "delta": info.get("delta"),
                "app_id": info.get("app_id"),
            }
        # 也从 leaderboard 获取
        for item in market_data.get("leaderboard", []):
            name = item.get("name", "")
            for comp_name in COMP_COLORS:
                if comp_name.lower() in name.lower() or name.lower() in comp_name.lower():
                    if comp_name not in rank_info:
                        rank_info[comp_name] = {
                            "rank": item.get("rank"),
                            "delta": item.get("delta"),
                            "app_id": item.get("app_id"),
                        }

    # 从 strategy_monitor 获取版本信息
    version_info = {}
    if strategy_data:
        for comp_name, comp_info in strategy_data.get("competitors", {}).items():
            if "error" not in comp_info:
                version_info[comp_name] = {
                    "version": comp_info.get("version", ""),
                    "release_notes": comp_info.get("release_notes", ""),
                    "has_changed": comp_info.get("has_changed", False),
                    "changes": comp_info.get("changes", []),
                }

    # 从 competitor_comments 获取评论摘要
    comment_summary = {}
    if comment_data:
        for comp_name, comp_info in comment_data.get("competitors", {}).items():
            total = sum(r.get("count", 0) for r in comp_info.get("regions", {}).values())
            if total > 0:
                regions_info = {}
                for region_code, region_data in comp_info.get("regions", {}).items():
                    regions_info[region_code] = {
                        "count": region_data.get("count", 0),
                        "negative_count": region_data.get("negative_count", region_data.get("count", 0)),
                        "labels": region_data.get("labels", {}),
                        "summary": region_data.get("summary", ""),
                    }
                comment_summary[comp_name] = {
                    "total": total,
                    "negative_total": sum(r.get("negative_count", r.get("count", 0)) for r in comp_info.get("regions", {}).values()),
                    "regions": regions_info,
                }

    # 从 competitor_details 获取深度分析
    for comp_name, detail in competitor_details.items():
        entry = result.get(comp_name, {})
        entry["detail_analysis"] = {
            "generated_at": detail.get("generated_at", ""),
            "days_analyzed": detail.get("days_analyzed", 7),
            "total_reviews": detail.get("total_reviews", 0),
            "feature_analysis": detail.get("feature_analysis", {}),
            "regions": {},
        }
        # 按地区汇总
        for region_code, region_data in detail.get("regions", {}).items():
            entry["detail_analysis"]["regions"][region_code] = {
                "label": region_data.get("label", region_code),
                "gp_count": region_data.get("gp_count", 0),
                "ios_count": region_data.get("ios_count", 0),
                "total": region_data.get("total", 0),
                "labels": region_data.get("labels", {}),
            }
        result[comp_name] = entry

    # 合并所有信息
    all_names = set(list(competitor_registry.keys()) + list(rank_info.keys()) + list(version_info.keys()) + list(comment_summary.keys()) + list(competitor_details.keys()))
    for name in all_names:
        if name not in result:
            result[name] = {}
        if name in rank_info:
            result[name]["rank"] = rank_info[name]
        if name in version_info:
            result[name]["version"] = version_info[name]
        if name in comment_summary:
            result[name]["comments"] = comment_summary[name]

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 构建周报数据 (JSON for frontend)
# ---------------------------------------------------------------------------

def build_weekly_review_json():
    """构建前端 WEEKLY_REVIEW_DATA 所需的 JSON 数据"""
    if not weekly_review_data:
        return "{}"
    # 只保留前端需要的数据，避免数据过大
    result = {
        "summary": weekly_review_data.get("summary", ""),
        "localization_insight": weekly_review_data.get("localization_insight", ""),
        "per_competitor": weekly_review_data.get("per_competitor", {}),
        "total_reviews": weekly_review_data.get("total_reviews", 0),
        "days_analyzed": weekly_review_data.get("days_analyzed", 7),
        "label_distribution": weekly_review_data.get("label_distribution", {}),
        "platform_distribution": weekly_review_data.get("platform_distribution", {}),
        "region_distribution": weekly_review_data.get("region_distribution", {}),
        "feature_keywords": weekly_review_data.get("feature_keywords", {}),
        "localization_review_count": weekly_review_data.get("localization_review_count", 0),
        "localization_by_region": weekly_review_data.get("localization_by_region", {}),
        "generated_at": weekly_review_data.get("generated_at", ""),
    }
    return json.dumps(result, ensure_ascii=False)


def build_commercial_json():
    if not commercial_data:
        return "{}"
    return json.dumps(commercial_data, ensure_ascii=False)


def build_commercial_weekly_json():
    if not commercial_weekly_data:
        return "{}"
    return json.dumps(commercial_weekly_data, ensure_ascii=False)


def build_community_data_json():
    if not community_data:
        return "{}"
    return json.dumps(community_data, ensure_ascii=False)


def build_rank_data_json():
    if not rank_data:
        return "{}"
    return json.dumps(rank_data, ensure_ascii=False)


def build_product_updates_json():
    if not product_updates:
        return '{"metrics": {}, "items": []}'
    return json.dumps(product_updates, ensure_ascii=False)


def build_reviews_analysis_json():
    if not reviews_analysis:
        return '{"metrics": {}, "items": []}'
    return json.dumps(reviews_analysis, ensure_ascii=False)


# ===========================================================================
# 生成 HTML
# ===========================================================================

def generate():
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 构建预警数据
    alerts = build_alerts()

    # 替换占位符
    replacements = {
        "<!-- REVIEW_DATA_PLACEHOLDER -->": build_review_data_json(),
        "<!-- COMPETITOR_DETAIL_DATA_PLACEHOLDER -->": build_competitor_detail_json(),
        "<!-- WEEKLY_REVIEW_DATA_PLACEHOLDER -->": build_weekly_review_json(),
        "<!-- COMMERCIAL_DATA_PLACEHOLDER -->": build_commercial_json(),
        "<!-- COMMERCIAL_WEEKLY_DATA_PLACEHOLDER -->": build_commercial_weekly_json(),
        "<!-- COMMUNITY_DATA_PLACEHOLDER -->": build_community_data_json(),
        "<!-- RANK_DATA_PLACEHOLDER -->": build_rank_data_json(),
        "<!-- PRODUCT_UPDATES_DATA_PLACEHOLDER -->": build_product_updates_json(),
        "<!-- REVIEWS_ANALYSIS_DATA_PLACEHOLDER -->": build_reviews_analysis_json(),

        "<!-- COMPETITOR_LIST_PLACEHOLDER -->": build_competitor_list(),

        "<!-- UPDATE_TIME_PLACEHOLDER -->": now_str(),
        "<!-- DATE_PLACEHOLDER -->": date_str(),
        "<!-- MONITORED_COUNT_PLACEHOLDER -->": str(metrics["monitored"]),
        "<!-- CHANGES_DETECTED_PLACEHOLDER -->": str(metrics["changes_detected"]),
        "<!-- MAX_RANK_DELTA_PLACEHOLDER -->": f"+{metrics['max_rank_delta']}" if metrics["max_rank_delta"] > 0 else str(metrics["max_rank_delta"]),
        "<!-- MAX_RANK_COMP_PLACEHOLDER -->": metrics["max_rank_comp"] if metrics["max_rank_comp"] else "—",
        "<!-- TOTAL_NEGATIVE_PLACEHOLDER -->": str(metrics["total_negative"]),
        "<!-- ALERT_STRIP_PLACEHOLDER -->": build_alert_strip_html(alerts),
        "<!-- ALERT_PAGE_PLACEHOLDER -->": build_alert_page_html(alerts),
        "<!-- ALERTS_DATA_PLACEHOLDER -->": build_alerts_data_json(alerts),
        "<!-- COMP_COLORS_PLACEHOLDER -->": json.dumps(COMP_COLORS, ensure_ascii=False),
        "<!-- ALERT_COUNT_PLACEHOLDER -->": str(len(alerts)),
        "<!-- FEED_ITEMS_PLACEHOLDER -->": build_feed_html(),
        "<!-- KEYWORD_CLOUD_PLACEHOLDER -->": build_keyword_cloud(),
        "<!-- RANK_TREND_PLACEHOLDER -->": build_rank_trend_svg(),
        "<!-- RANK_TABLE_PLACEHOLDER -->": build_rank_table(),
        "<!-- BASELINE_COMPARISON_PLACEHOLDER -->": build_baseline_comparison_section(),
        "<!-- MULTI_SOURCE_RANK_PLACEHOLDER -->": build_multi_source_rank_section(),
        "<!-- MULTI_SOURCE_REVENUE_PLACEHOLDER -->": build_multi_source_revenue_section(),
        "<!-- MULTI_SOURCE_DATA_PLACEHOLDER -->": json.dumps(build_multi_source_json(), ensure_ascii=False),
        # PRODUCT_PAGE_PLACEHOLDER 已废弃（page-product 改为 PRODUCT_UPDATES JSON-driven 渲染）
        "<!-- PRODUCT_PAGE_PLACEHOLDER -->": "",
        # REVIEW_PAGE_PLACEHOLDER 已废弃（page-reviews 改为 REVIEWS_ANALYSIS JSON-driven 渲染）
        "<!-- REVIEW_PAGE_PLACEHOLDER -->": "",
        "<!-- WEEKLY_UPDATES_PLACEHOLDER -->": str(metrics["changes_detected"]),
        "<!-- WEEKLY_NEGATIVE_PLACEHOLDER -->": str(metrics["total_negative"]),
    }

    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] 看板已生成: {OUTPUT_HTML}")
    return OUTPUT_HTML

# ===========================================================================
# 主入口
# ===========================================================================

if __name__ == "__main__":
    # 可选：先同步数据
    if "--sync" in sys.argv:
        print("[INFO] 正在同步数据...")
        scripts = {
            "competitor_comment": str(_PROJECT_ROOT / "competitor_comment" / "auto_report.py"),
            "strategy_monitor": str(_PROJECT_ROOT / "strategy_monitor" / "run_headless.py"),
            "market_rank": str(_PROJECT_ROOT / "market_rank" / "run_headless.py"),
        }
        for name, path in scripts.items():
            if os.path.exists(path):
                print(f"  运行 {name}...")
                subprocess.run([sys.executable, path], capture_output=True, timeout=300, cwd=os.path.dirname(path))
        # 数据源已刷新，重新跑聚合层并刷新派生视图
        _dashboard_data = _ensure_dashboard_data()
        strategy_data = _adapt_strategy(_dashboard_data)
        market_data = _adapt_market(_dashboard_data)
        comment_data = _adapt_comments(_dashboard_data)
        ranking_history = _adapt_ranking_history(_dashboard_data)
        competitor_registry = _dashboard_data.get("competitor_registry") or {}
        competitor_details = _adapt_competitor_details(_dashboard_data)
        weekly_review_data = _dashboard_data.get("weekly", {}).get("comment") or {}
        commercial_data = _adapt_commercial(_dashboard_data)
        commercial_weekly_data = _dashboard_data.get("weekly", {}).get("commercial") or {}
        community_data = _adapt_community(_dashboard_data)
        rank_data = _adapt_rank_view(_dashboard_data)
        product_updates = _adapt_product_updates(_dashboard_data)
        reviews_analysis = _adapt_reviews_analysis(_dashboard_data)
        metrics = compute_metrics()

    output = generate()
    print(f"\n使用浏览器打开: file://{output}")
