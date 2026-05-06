#!/usr/bin/env python3
"""build_demo_html.py — 把当前 MySQL 数据导出成单 HTML demo 文件。

输出：data/demo.html — 双击打开即可（无需后端 / 前端 server）。
内含：
  - 14 个页面（Overview / AlertCenter / 4 数据 / 5 内容 / 3 系统）
  - 全部 sidebar 导航 + hash 路由
  - 数据嵌入 <script> 内（来自当前 MySQL，已 seed_demo 后）
  - Tailwind CDN（首次加载需要联网，之后浏览器缓存）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from shared.env_loader import load_all
    load_all()
except Exception:
    pass

from shared import db   # noqa: E402
from sqlalchemy import text   # noqa: E402

OUT = _ROOT / "data" / "demo.html"


# ─────────────────── 数据导出 ───────────────────


def _to_jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if v is not None and v.__class__.__name__ == "Decimal":
        return float(v)
    return v


def _rows(s, sql: str, **params):
    rows = s.execute(text(sql), params).fetchall()
    return [{k: _to_jsonable(v) for k, v in r._mapping.items()} for r in rows]


_API_BASE = os.environ.get("DEMO_API_BASE", "http://127.0.0.1:8899")


def _api_get(path: str) -> dict:
    """打 v2 API，与 live 前端拿同一份数据；backend 不可达就返回 {}。"""
    import urllib.request as _urlreq, urllib.error as _urlerr
    url = f"{_API_BASE}{path}"
    try:
        req = _urlreq.Request(url, headers={"Accept": "application/json"})
        with _urlreq.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (_urlerr.URLError, json.JSONDecodeError, OSError) as e:
        print(f"  ✗ API {path} 失败: {e}（demo 该板块可能空）", file=sys.stderr)
        return {}


def export_data() -> dict:
    """从运行中的 v2 backend (默认 :8899) 拉数据，保证 demo 和实时面板一致。

    各 endpoint 已在 dashboard_server.py 实现 fallback（alerts/candidates 表空时
    从 dashboard_data.json + market_rank_snapshots 派生），demo 拿到的就是前端看到的。
    """
    print("[*] 从 v2 API 拉数据 ...", file=sys.stderr)
    out = {
        "alerts":           _api_get("/api/alerts?limit=200").get("alerts", []),
        "rank":             _api_get("/api/rank?limit=200").get("rankings", []),
        "iap":              _api_get("/api/iap?limit=800").get("iap_items", []),
        "ads":              _api_get("/api/ads?limit=500").get("ads", []),
        "website":          _api_get("/api/website?limit=200").get("website", []),
        "reviews":          _api_get("/api/reviews?limit=500").get("reviews", []),
        "community":        _api_get("/api/community?limit=100").get("posts", []),
        "candidates":       _api_get("/api/candidates?limit=100").get("candidates", []),
        "failed_ai_jobs":   _api_get("/api/failed-ai-jobs?limit=50").get("jobs", []),
        "sync_log":         _api_get("/api/sync-log?limit=50").get("logs", []),
        "news":             _api_get("/api/news?limit=50").get("news", []),
        "status":           _api_get("/api/status") or {},
    }
    return out


def _legacy_export_data_via_sql() -> dict:
    """旧版直接打 MySQL 的实现 — 与 live 面板不一致（不再使用，留作参考）。"""
    if not db.is_mysql_enabled():
        raise RuntimeError("MYSQL_DSN 未配置")

    with db.session() as s:
        out = {}

        # alerts
        out["alerts"] = _rows(s, """
            SELECT id, alert_type, severity, app_name, competitor_id,
                   metadata_json, title, rule_triggered, fired_at, status
            FROM alerts
            WHERE fired_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            ORDER BY fired_at DESC LIMIT 200
        """)
        for a in out["alerts"]:
            try:
                a["metadata"] = json.loads(a.pop("metadata_json") or "{}")
            except Exception:
                a["metadata"] = {}

        # rank
        out["rank"] = _rows(s, """
            SELECT m.id, m.source, m.region_code, c.name AS competitor,
                   m.name, m.rank_value, m.delta, m.downloads, m.downloads_num,
                   m.revenue_num, m.snapshot_date, m.fetched_at
            FROM market_rank_snapshots m
            LEFT JOIN competitors c ON c.id = m.competitor_id
            WHERE m.snapshot_date >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
              AND c.name IS NOT NULL
            ORDER BY m.snapshot_date DESC, m.rank_value ASC
            LIMIT 500
        """)

        # iap
        out["iap"] = _rows(s, """
            SELECT i.id, c.name AS competitor, i.region_code, i.name,
                   i.price, i.price_num, i.currency, i.category, i.fetched_at
            FROM iap_items i JOIN competitors c ON c.id = i.competitor_id
            ORDER BY i.fetched_at DESC LIMIT 800
        """)

        # ads
        out["ads"] = _rows(s, """
            SELECT a.id, c.name AS competitor, a.region_code AS region,
                   a.ad_id, a.text AS body_text, a.start_date,
                   a.platform, a.page_name, a.fetched_at
            FROM ad_creatives a JOIN competitors c ON c.id = a.competitor_id
            ORDER BY a.fetched_at DESC LIMIT 500
        """)

        # website
        rows = _rows(s, """
            SELECT w.id, c.name AS competitor, w.domain, w.snapshot_month,
                   w.monthly_visits, w.monthly_visits_num,
                   w.avg_visit_duration, w.avg_visit_duration_sec,
                   w.pages_per_visit, w.bounce_rate,
                   w.global_rank, w.country_rank, w.country_rank_country, w.category_rank,
                   w.male_share, w.female_share,
                   w.top_countries_json, w.similar_sites_json, w.fetched_at
            FROM website_traffic w JOIN competitors c ON c.id = w.competitor_id
            ORDER BY c.name
        """)
        for r in rows:
            for k in ("top_countries_json", "similar_sites_json"):
                v = r.pop(k, None)
                key = k.replace("_json", "")
                try:
                    r[key] = json.loads(v) if v else []
                except Exception:
                    r[key] = []
        out["website"] = rows

        # reviews（仅 labeled，最近 7d，限 500 条）
        rev_rows = _rows(s, """
            SELECT r.id, c.name AS competitor, r.region_code, r.platform,
                   r.score, r.version, r.content, r.label, r.language,
                   r.translated_text, r.at, r.labeled_at
            FROM reviews r JOIN competitors c ON c.id = r.competitor_id
            WHERE r.labeled_at IS NOT NULL
              AND r.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
            ORDER BY r.at DESC LIMIT 500
        """)
        # 加 entities 关联
        if rev_rows:
            ids = [r["id"] for r in rev_rows]
            placeholders = ",".join(str(i) for i in ids)
            ents = s.execute(text(
                f"SELECT review_id, canonical_id, entity_type, raw_value "
                f"FROM comment_entities WHERE review_id IN ({placeholders})"
            )).fetchall()
            by_rid: dict = {}
            for er in ents:
                by_rid.setdefault(er.review_id, []).append({
                    "canonical_id": er.canonical_id,
                    "type": er.entity_type,
                    "raw_value": er.raw_value,
                })
            for r in rev_rows:
                r["entities"] = by_rid.get(r["id"], [])
        out["reviews"] = rev_rows

        # community
        out["community"] = _rows(s, """
            SELECT p.id, c.name AS competitor, p.source, p.post_id, p.subreddit,
                   p.title, p.selftext, p.score, p.num_comments, p.url,
                   p.created_utc, p.fetched_at
            FROM community_posts p JOIN competitors c ON c.id = p.competitor_id
            ORDER BY p.score DESC, p.created_utc DESC LIMIT 100
        """)

        # candidates
        rows = _rows(s, """
            SELECT a.id, a.app_id, a.platform, a.bundle_id, a.name, a.publisher,
                   a.category, a.description_excerpt, a.matched_keywords,
                   a.is_relevant, a.topic, a.categories, a.confidence,
                   a.rejection_reason, a.classified_at
            FROM app_classifications a
            WHERE a.is_relevant = 1
              AND a.confidence >= 0.85
              AND a.topic IN ('football','multi_sport')
              AND NOT EXISTS (
                  SELECT 1 FROM competitors c
                  WHERE c.ios_app_id COLLATE utf8mb4_unicode_ci = a.app_id
                    AND a.platform = 'ios'
              )
            ORDER BY a.confidence DESC LIMIT 100
        """)
        for r in rows:
            for k in ("matched_keywords", "categories"):
                try:
                    r[k] = json.loads(r[k]) if r.get(k) else []
                except Exception:
                    r[k] = []
        out["candidates"] = rows

        # failed_ai_jobs
        rows = _rows(s, """
            SELECT id, task_name, payload_json, error_msg, error_kind,
                   attempts, first_failed_at, last_attempt_at, resolved_at
            FROM failed_ai_jobs ORDER BY last_attempt_at DESC LIMIT 50
        """)
        for r in rows:
            try:
                r["payload"] = json.loads(r.pop("payload_json") or "{}")
            except Exception:
                r["payload"] = {}
        out["failed_ai_jobs"] = rows

        # sync_log
        out["sync_log"] = _rows(s, """
            SELECT id, script, label, competitor, started_at, finished_at,
                   duration_sec, success, error_kind, stdout_tail, stderr_tail, cmd
            FROM sync_log ORDER BY started_at DESC LIMIT 50
        """)

        # news 走 JSON 文件
        news_path = _ROOT / "data" / "async_google_news.json"
        news = []
        if news_path.exists():
            try:
                payload = json.loads(news_path.read_text(encoding="utf-8"))
                for rec in payload:
                    app = rec.get("competitor")
                    for it in (rec.get("data") or {}).get("items", []):
                        news.append({
                            "competitor": app,
                            "title": it.get("title"),
                            "link": it.get("link"),
                            "source": it.get("source"),
                            "desc": it.get("desc"),
                            "pub_iso": it.get("pub_iso"),
                            "is_biz": bool(it.get("is_biz")),
                        })
                news.sort(key=lambda x: x.get("pub_iso") or "", reverse=True)
            except Exception:
                pass
        out["news"] = news[:50]

        # status mock
        out["status"] = {
            "sources": {src: {"status": "ok", "last_success": datetime.utcnow().isoformat()}
                        for src in ["appstore_rank", "androidrank", "comment_fetch", "reddit",
                                    "iap_pricing", "google_news", "strategy_monitor",
                                    "appmagic", "fb_adlib", "sensor_tower", "similarweb_traffic",
                                    "ai_pipeline"]},
            "retry_queue_size": 2,
            "failed_ai_jobs": {"comment_label": 2, "entity_extract": 1,
                               "alert_title": 1, "app_classifier": 1},
            "candidates_count": len(out["candidates"]),
            "alerts_new_7d": sum(1 for a in out["alerts"] if a.get("status") == "new"),
            "ts": datetime.utcnow().isoformat(),
        }
        # twitter 标 skip 显示警告色
        out["status"]["sources"]["twitter"] = {"status": "skip", "last_error": "fapi quota"}

        return out


# ─────────────────── HTML 模板 ───────────────────


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>INTEL-OPS · 竞品情报 Demo</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
:root {
  --brand-50:#E6FBE9; --brand-500:#00D616; --brand-600:#00B011; --brand-700:#008A0D;
  --info:#185FA5; --success:#1D9E75; --warning:#EF9F27; --danger:#E24B4A;
}
body { font-family: ui-sans-serif, system-ui, "PingFang SC", "Microsoft YaHei", sans-serif; }
.tabular-nums { font-variant-numeric: tabular-nums; }
.font-mono { font-family: "JetBrains Mono", ui-monospace, Consolas, monospace; }
.text-2xs { font-size: 10px; line-height: 1.4; }
.bg-brand-50 { background-color: var(--brand-50); }
.text-brand-500 { color: var(--brand-500); }
.text-brand-600 { color: var(--brand-600); }
.text-brand-700 { color: var(--brand-700); }
.bg-info { background-color: #E6F1FB; }
.text-info { color: var(--info); }
.text-success { color: var(--success); }
.text-warning { color: var(--warning); }
.text-danger { color: var(--danger); }
.bg-pill-blue { background:#E6F1FB; color:#042C53; }
.bg-pill-green{ background:#EAF3DE; color:#173404; }
.bg-pill-amber{ background:#FAEEDA; color:#412402; }
.bg-pill-red  { background:#FCEBEB; color:#501313; }
.bg-pill-purple{ background:#EEEDFE; color:#26215C; }
.bg-pill-teal { background:#E1F5EE; color:#04342C; }
.bg-pill-pink { background:#FBEAF0; color:#4B1528; }
.bg-pill-gray { background:#F4F3F0; color:#5F5E5A; }
.row-baseline { background-color: rgba(230, 241, 251, 0.5); }
table { border-collapse: collapse; }
.btn { display:inline-flex; align-items:center; gap:.25rem; padding:0 .5rem; height:24px; border-radius:4px; font-size:11px; cursor:pointer; transition:background-color .15s; }
.btn-active { background:#1f2937; color:white; font-weight:500; }
.btn-idle { background:rgba(0,0,0,.05); color:#6b7280; }
.btn-idle:hover { background:rgba(0,0,0,.1); color:#111; }
.tab-active { background:rgba(0,214,22,.08); color:var(--brand-700); font-weight:500; }
.tab-idle:hover { background:rgba(0,0,0,.04); }
.line-clamp-2 { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.line-clamp-3 { display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
</style>
</head>
<body class="bg-white text-gray-900 text-[13px]">

<div id="app" class="flex min-h-screen">
  <!-- Sidebar -->
  <aside class="w-56 border-r border-gray-200 shrink-0">
    <div class="h-12 px-3 flex items-center border-b border-gray-100">
      <span class="text-sm font-semibold tracking-tight">INTEL-OPS</span>
      <span class="ml-auto text-2xs text-gray-400 font-mono">demo</span>
    </div>
    <nav class="px-2 py-2 space-y-3" id="sidebar"></nav>
  </aside>

  <!-- Main -->
  <main class="flex-1 min-w-0 px-6 py-5 overflow-auto">
    <div id="page"></div>
  </main>
</div>

<script>
// ============== 数据 ==============
const DATA = __DATA__;

// ============== 工具 ==============
const $ = (id) => document.getElementById(id);
const html = (strings, ...vals) => strings.reduce((acc, s, i) => acc + s + (vals[i] != null ? vals[i] : ''), '');
const escape = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
const fmtNum = (n) => {
  if (n == null) return '—';
  if (n >= 1e9) return (n/1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
  return String(n);
};
const fmtPct = (p, d=1) => p == null ? '—' : (p*100).toFixed(d) + '%';
const fmtDate = (s) => {
  if (!s) return '—';
  const d = new Date(s);
  return d.toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
};
const fmtDateOnly = (s) => {
  if (!s) return '—';
  return new Date(s).toLocaleDateString('zh-CN', { month:'2-digit', day:'2-digit' });
};

const COMPETITORS = ["SofaScore","FlashScore","OneFootball","365Scores","Fotmob",
                     "LiveScore","AiScore","BeSoccer","310Scores"];
const BASELINE = "AllFootball";
const REGION_LABEL = {
  us:"美国 🇺🇸", gb:"英国 🇬🇧", de:"德国 🇩🇪", fr:"法国 🇫🇷", es:"西班牙 🇪🇸", it:"意大利 🇮🇹",
  br:"巴西 🇧🇷", mx:"墨西哥 🇲🇽", ng:"尼日利亚 🇳🇬", sa:"沙特 🇸🇦", ae:"阿联酋 🇦🇪", jp:"日本 🇯🇵",
};
const ALERT_TYPE_LABELS = {
  ranking:"排名异动", commercial:"商业变动", news:"商业新闻", release:"产品发布",
  rating:"评分变化", churn:"流失信号", ads:"广告投放",
};
const LABEL_DISPLAY = {
  complaint:        { text:"问题抱怨",   pill:"bg-pill-red" },
  feature_request:  { text:"功能请求",   pill:"bg-pill-blue" },
  competitor_compare:{ text:"竞品对比", pill:"bg-pill-amber" },
  churn_signal:     { text:"流失信号",   pill:"bg-pill-purple" },
  positive:         { text:"正向反馈",   pill:"bg-pill-green" },
  other:            { text:"其他",       pill:"bg-pill-gray" },
};
const TOPIC_LABEL = { football:"足球", basketball:"篮球", multi_sport:"综合体育", non_sport:"非体育" };
const CAT_LABEL = { news:"新闻", score:"比分", prediction:"预测", tipster:"专家推荐", betting:"博彩", analytics:"数据分析", community:"社区", video:"视频" };

// ============== 路由 ==============
const ROUTES = [
  { hash: "#/overview", label: "总览看点", icon: "📊", group: 0 },
  { hash: "#/alerts",   label: "预警中心", icon: "🚨", group: 0, badge: () => DATA.status.alerts_new_7d },

  { hash: "#/rankings", label: "排名异动", icon: "📈", group: 1 },
  { hash: "#/revenue",  label: "收入下载", icon: "💰", group: 1 },
  { hash: "#/iap",      label: "IAP 内购", icon: "🏷️", group: 1 },
  { hash: "#/website",  label: "网站数据", icon: "🌐", group: 1 },

  { hash: "#/releases", label: "产品动态", icon: "🚀", group: 2 },
  { hash: "#/reviews",  label: "GP 评论",  icon: "💬", group: 2 },
  { hash: "#/social",   label: "社媒评论", icon: "🧵", group: 2 },
  { hash: "#/news",     label: "商业新闻", icon: "📰", group: 2 },
  { hash: "#/ads",      label: "广告投放", icon: "📣", group: 2 },

  { hash: "#/candidates", label: "候选发现",  icon: "🔍", group: 3, badge: () => DATA.status.candidates_count },
  { hash: "#/failed",     label: "AI 失败队列", icon: "⚠️", group: 3,
    badge: () => Object.values(DATA.status.failed_ai_jobs).reduce((a,b) => a+b, 0) },
  { hash: "#/sync",       label: "同步日志",     icon: "📜", group: 3 },
];
const GROUP_LABELS = ["", "数据类", "内容类", "系统"];

function renderSidebar() {
  const groups = {};
  ROUTES.forEach(r => { (groups[r.group] = groups[r.group] || []).push(r); });
  const cur = window.location.hash || "#/overview";
  $('sidebar').innerHTML = Object.keys(groups).map(g => {
    const label = GROUP_LABELS[g];
    return `
      ${label ? `<div class="px-2 pb-1 text-2xs uppercase tracking-wider text-gray-400">${label}</div>` : ''}
      <div class="space-y-0.5">
        ${groups[g].map(r => {
          const active = r.hash === cur;
          const badge = r.badge ? r.badge() : null;
          return `<a href="${r.hash}" class="flex items-center gap-2 px-2 h-8 rounded text-sm ${active ? 'tab-active' : 'tab-idle'}">
            <span class="w-4">${r.icon}</span>
            <span class="flex-1 truncate">${r.label}</span>
            ${badge ? `<span class="px-1.5 h-4 min-w-4 text-2xs font-medium rounded bg-[#E24B4A] text-white inline-flex items-center justify-center">${badge > 99 ? '99+' : badge}</span>` : ''}
          </a>`;
        }).join('')}
      </div>
    `;
  }).join('');
}

function renderPage() {
  const hash = window.location.hash || "#/overview";
  const renderers = {
    "#/overview": renderOverview, "#/alerts": renderAlerts,
    "#/rankings": renderRankings, "#/revenue": renderRevenue,
    "#/iap": renderIap, "#/website": renderWebsite,
    "#/releases": renderReleases, "#/reviews": renderReviews,
    "#/social": renderSocial, "#/news": renderNews, "#/ads": renderAds,
    "#/candidates": renderCandidates, "#/failed": renderFailed, "#/sync": renderSync,
  };
  const fn = renderers[hash] || renderOverview;
  $('page').innerHTML = fn();
  renderSidebar();
}

window.addEventListener('hashchange', renderPage);
window.addEventListener('DOMContentLoaded', renderPage);

// ============== 共享 ==============
function pageHeader(title, subtitle) {
  return `<div class="mb-4">
    <h1 class="text-[22px] font-semibold tracking-tight">${escape(title)}</h1>
    ${subtitle ? `<p class="text-xs text-gray-500 mt-1">${escape(subtitle)}</p>` : ''}
  </div>`;
}
function kpi(label, value, hint) {
  return `<div class="border border-gray-200 rounded-md bg-white p-3">
    <div class="text-2xs text-gray-400 uppercase tracking-wider">${escape(label)}</div>
    <div class="text-[22px] font-semibold tabular-nums mt-1">${value}</div>
    ${hint ? `<div class="text-2xs text-gray-400 mt-0.5">${escape(hint)}</div>` : ''}
  </div>`;
}
function kpiRow(items) {
  return `<div class="grid grid-cols-4 gap-3 mb-4">${items.join('')}</div>`;
}
function pill(text, color="bg-pill-gray") {
  return `<span class="inline-flex items-center px-1.5 h-5 rounded text-2xs font-medium ${color}">${escape(text)}</span>`;
}
function severityBar(s) {
  const c = { high:'#E24B4A', mid:'#EF9F27', low:'rgba(0,0,0,.2)' }[s] || '#999';
  return `<span class="inline-block w-1 self-stretch rounded-sm" style="background:${c};"></span>`;
}
function emptyHint(msg="暂无数据") {
  return `<div class="text-center py-12 text-sm text-gray-400">${escape(msg)}</div>`;
}

// ============== 0. 同步状态条 ==============
function syncStatusBar() {
  const sources = ["appstore_rank","androidrank","comment_fetch","reddit","twitter",
    "iap_pricing","google_news","strategy_monitor","appmagic","fb_adlib","sensor_tower",
    "similarweb_traffic","ai_pipeline"];
  const COLOR = { ok:"text-success", fail:"text-danger", pending:"text-warning", skip:"text-gray-400" };
  const ICON =  { ok:"●", fail:"✕", pending:"◔", skip:"○" };
  const failed = Object.values(DATA.status.failed_ai_jobs).reduce((a,b)=>a+b,0);
  return `<div class="flex items-center gap-3 px-3 py-2 border border-gray-200 rounded-md bg-white text-xs mb-4">
    <div class="flex items-center gap-1.5 ${COLOR.ok} shrink-0"><span>●</span><span class="font-medium">同步 OK</span></div>
    <div class="text-gray-400 shrink-0">retry: ${DATA.status.retry_queue_size} · failed AI: ${failed}</div>
    <div class="flex flex-wrap gap-1 flex-1 min-w-0">
      ${sources.map(s => {
        const st = (DATA.status.sources[s]?.status) || "ok";
        return `<span class="inline-flex items-center gap-1 px-1.5 h-5 rounded bg-gray-50 text-2xs ${COLOR[st]||''}">${ICON[st]||'?'}<span class="font-mono">${s}</span></span>`;
      }).join('')}
    </div>
  </div>`;
}

// ============== 1. Overview ==============
function renderOverview() {
  const top4Ranking = DATA.alerts.filter(a => a.alert_type === 'ranking').slice(0, 4);
  const af = DATA.rank.find(r => r.competitor === BASELINE && r.source === 'sensor_tower');
  const competitorRank = DATA.rank.filter(r => r.competitor && r.competitor !== BASELINE && r.source === 'sensor_tower');
  const revenueChamp = [...competitorRank].sort((a,b)=>(b.revenue_num||0)-(a.revenue_num||0))[0];
  const top3Iap = DATA.alerts.filter(a => a.alert_type === 'commercial').slice(0, 3);
  const wAf = DATA.website.find(w => w.competitor === BASELINE);
  const wTop = DATA.website.filter(w => w.competitor !== BASELINE)
    .sort((a,b) => (b.monthly_visits_num||0) - (a.monthly_visits_num||0))[0];
  const releases = DATA.alerts.filter(a => a.alert_type === 'release').slice(0, 3);
  const reviews3 = DATA.reviews.slice(0, 3);
  const social2 = DATA.community.slice(0, 2);
  const newsTop = DATA.news[0];
  const adsByApp = {};
  DATA.ads.forEach(ad => { if (!adsByApp[ad.competitor] && ad.body_text) adsByApp[ad.competitor] = ad; });
  const ads4 = Object.values(adsByApp).slice(0, 4);

  const card = (title, cat, href, meta, body) => {
    const catCls = { data:'bg-pill-blue', content:'bg-pill-purple' }[cat] || 'bg-pill-gray';
    return `<div class="border border-gray-200 rounded-md bg-white p-4 flex flex-col">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-base font-semibold tracking-tight">${title}</span>
        <span class="text-2xs px-1.5 py-0.5 rounded font-medium ${catCls}">${cat === 'data' ? '数据' : '内容'}</span>
        <a href="${href}" class="ml-auto text-2xs text-gray-400 hover:text-gray-700">详情 →</a>
      </div>
      ${meta ? `<div class="text-xs text-gray-500 mb-2">${meta}</div>` : ''}
      <div class="flex-1">${body}</div>
    </div>`;
  };

  return `${pageHeader("总览看点", "9 个板块今天的关键信号 · AllFootball 为数据基准")}
    ${syncStatusBar()}
    <h2 class="text-2xs uppercase tracking-wider text-gray-400 mb-2">数据类</h2>
    <div class="grid grid-cols-2 gap-3 mb-4">
      ${card("排名异动", "data", "#/rankings", `24h 内 ${DATA.alerts.filter(a=>a.alert_type==='ranking').length} 条异动`,
        top4Ranking.length ? `<ul class="space-y-1">${top4Ranking.map(a => {
          const md = a.metadata; const up = (md.change||0) > 0;
          return `<li class="flex items-center gap-2 text-xs py-1">
            <span class="font-medium truncate flex-1">${escape(a.app_name)}</span>
            <span class="text-2xs text-gray-400">${REGION_LABEL[md.region] || (md.region||'').toUpperCase()}</span>
            <span class="tabular-nums text-gray-500">#${md.old_rank} → #${md.new_rank}</span>
            <span class="tabular-nums w-12 text-right ${up ? 'text-success' : 'text-danger'}">${up ? '↑' : '↓'} ${Math.abs(md.change||0)}</span>
          </li>`;
        }).join('')}</ul>` : '<div class="text-xs text-gray-400 py-3">无异动</div>')}

      ${card("收入下载", "data", "#/revenue", "美区 sensor_tower 估算",
        `<div class="space-y-1 text-xs">
          <div class="flex items-center gap-2 py-1"><span class="font-medium text-info w-20">${BASELINE}</span><span class="text-gray-400">月下载</span><span class="ml-auto font-mono tabular-nums">${af ? fmtNum(af.downloads_num) : '—'}</span></div>
          <div class="flex items-center gap-2 py-1"><span class="font-medium text-info w-20">${BASELINE}</span><span class="text-gray-400">月收入</span><span class="ml-auto font-mono tabular-nums">$${af ? fmtNum(af.revenue_num) : '—'}</span></div>
          <div class="border-t border-gray-100 my-1"></div>
          ${revenueChamp ? `<div class="flex items-center gap-2 py-1"><span class="text-gray-400 w-20">收入冠军</span><span class="font-medium truncate">${escape(revenueChamp.competitor)}</span><span class="ml-auto font-mono tabular-nums">$${fmtNum(revenueChamp.revenue_num)}</span></div>` : ''}
        </div>`)}

      ${card("IAP 内购", "data", "#/iap", `24h 内 ${top3Iap.length} 条价格变动`,
        top3Iap.length ? `<ul class="space-y-1">${top3Iap.map(a => {
          const md = a.metadata; const up = (md.change_pct||0) > 0;
          return `<li class="text-xs py-1"><div class="flex items-center gap-2"><span class="font-medium truncate flex-1">${escape(a.app_name)} · ${escape(md.iap_name)}</span><span class="${up ? 'text-danger' : 'text-success'} tabular-nums">${up ? '↑' : '↓'} ${Math.abs((md.change_pct||0)).toFixed(0)}%</span></div><div class="text-2xs text-gray-400 tabular-nums mt-0.5">$${(md.old_price_usd||0).toFixed(2)} → $${(md.new_price_usd||0).toFixed(2)} · 影响 ${md.regions_count||0} 区</div></li>`;
        }).join('')}</ul>` : '<div class="text-xs text-gray-400 py-3">无变动</div>')}

      ${card("网站数据", "data", "#/website", wAf ? wAf.snapshot_month : '—',
        wAf ? `<div class="text-xs space-y-1"><div class="grid grid-cols-2 gap-2">
          <div><div class="text-2xs text-gray-400">月访问</div><div class="font-mono tabular-nums">${escape(wAf.monthly_visits)}</div></div>
          <div><div class="text-2xs text-gray-400">平均停留</div><div class="font-mono tabular-nums">${escape(wAf.avg_visit_duration)}</div></div>
          <div><div class="text-2xs text-gray-400">跳出率</div><div class="font-mono tabular-nums">${fmtPct(wAf.bounce_rate)}</div></div>
          <div><div class="text-2xs text-gray-400">全球排名</div><div class="font-mono tabular-nums">#${(wAf.global_rank||0).toLocaleString()}</div></div>
        </div>${wTop ? `<div class="border-t border-gray-100 my-1"></div><div class="flex items-center gap-2"><span class="text-2xs text-gray-400 w-16">竞品 Top1</span><span class="font-medium truncate">${escape(wTop.competitor)}</span><span class="ml-auto font-mono tabular-nums">${escape(wTop.monthly_visits)}</span></div>` : ''}</div>` : '<div class="text-xs text-gray-400 py-3">暂无</div>')}
    </div>

    <h2 class="text-2xs uppercase tracking-wider text-gray-400 mb-2">内容类</h2>
    <div class="grid grid-cols-2 gap-3">
      ${card("产品动态", "content", "#/releases", `7d 内 ${DATA.alerts.filter(a=>a.alert_type==='release').length} 次发版`,
        releases.length ? `<ul class="space-y-1">${releases.map(a => {
          const md = a.metadata;
          return `<li class="text-xs py-1"><div class="flex items-baseline gap-2"><span class="font-medium truncate">${escape(a.app_name)}</span><span class="font-mono text-2xs text-gray-400">${escape(md.version || '')}</span></div></li>`;
        }).join('')}</ul>` : '<div class="text-xs text-gray-400 py-3">无新版本</div>')}

      ${card("GP 评论", "content", "#/reviews", `近 3d 已标 ${DATA.reviews.length} 条`,
        reviews3.length ? `<ul class="space-y-2">${reviews3.map(r => {
          const ld = LABEL_DISPLAY[r.label] || LABEL_DISPLAY.other;
          return `<li class="text-xs"><div class="flex items-center gap-1.5 mb-0.5">${pill(ld.text, ld.pill)}<span class="text-2xs text-gray-400">${escape(r.competitor)} · ${escape(r.region_code)} · ${r.score||'?'}★</span></div><div class="line-clamp-2 leading-snug">${escape((r.translated_text || r.content || '').slice(0, 200))}</div></li>`;
        }).join('')}</ul>` : '<div class="text-xs text-gray-400 py-3">暂无</div>')}

      ${card("社媒评论", "content", "#/social", `${DATA.community.length} 条最近高热`,
        social2.length ? `<ul class="space-y-2">${social2.map(p => `
          <li class="text-xs">
            <div class="flex items-baseline gap-1.5 mb-0.5"><span class="font-medium truncate">${escape(p.competitor)}</span>${p.subreddit ? `<span class="text-2xs text-gray-400 font-mono">r/${escape(p.subreddit)}</span>` : ''}<span class="ml-auto text-2xs text-gray-400 tabular-nums">↑ ${p.score||0} · 💬 ${p.num_comments||0}</span></div>
            <div class="line-clamp-2 leading-snug">${escape((p.title || '').slice(0, 200))}</div>
          </li>`).join('')}</ul>` : '<div class="text-xs text-gray-400 py-3">暂无</div>')}

      ${card("商业新闻", "content", "#/news", `近 7d ${DATA.news.length} 条`,
        newsTop ? `<article class="text-xs"><div class="flex items-baseline gap-1.5 mb-1"><span class="font-medium">${escape(newsTop.competitor)}</span><span class="text-2xs text-gray-400">${escape(newsTop.source)}</span>${newsTop.is_biz ? '<span class="text-2xs px-1 rounded bg-pill-amber">⭐ biz</span>' : ''}</div><div class="font-medium leading-snug line-clamp-2">${escape(newsTop.title || '')}</div>${newsTop.desc ? `<p class="mt-1 text-2xs text-gray-400 line-clamp-2 leading-snug">${escape(newsTop.desc.slice(0, 200))}</p>` : ''}</article>` : '<div class="text-xs text-gray-400 py-3">暂无</div>')}

      ${card("广告投放", "content", "#/ads", `${DATA.ads.length} 条活跃创意`,
        ads4.length ? `<div class="grid grid-cols-2 gap-x-4 gap-y-2">${ads4.map(ad => `
          <div class="text-xs"><div class="flex items-center gap-1.5 mb-1"><span class="font-medium">${escape(ad.competitor)}</span><span class="text-2xs text-gray-400 font-mono uppercase">${escape(ad.region)}</span></div><p class="text-gray-500 line-clamp-3 leading-snug">${escape(ad.body_text || '')}</p></div>
        `).join('')}</div>` : '<div class="text-xs text-gray-400 py-3">暂无</div>').replace(/<div class="border/, '<div class="col-span-2 border')}
    </div>
  `;
}

// ============== 2. Alerts ==============
function renderAlerts() {
  const types = ["ranking","commercial","news","release","rating","churn","ads"];
  const grouped = {};
  DATA.alerts.forEach(a => { (grouped[a.alert_type] = grouped[a.alert_type] || []).push(a); });
  return `${pageHeader("预警中心", `${DATA.alerts.length} 条事件 · 7 类规则触发 + AI 写 ≤50 字事实陈述`)}
    <div class="space-y-3">
      ${types.filter(t => grouped[t]?.length).map(t => `
        <section class="border border-gray-200 rounded-md bg-white overflow-hidden">
          <header class="flex items-center justify-between px-3 h-9 bg-gray-50 border-b border-gray-100">
            <div class="flex items-center gap-2"><span class="text-sm font-medium">${ALERT_TYPE_LABELS[t]}</span><span class="text-2xs text-gray-400">${grouped[t].length} 条</span></div>
            <span class="text-2xs text-gray-400 font-mono">${t}</span>
          </header>
          <div class="divide-y divide-gray-100">${grouped[t].map(a => `
            <div class="flex items-stretch gap-2 py-2 px-2 ${a.status === 'new' ? '' : 'opacity-60'}">
              ${severityBar(a.severity)}
              <div class="flex-1 min-w-0">
                <div class="text-sm truncate font-medium">${escape(a.title || a.app_name)}</div>
                <div class="text-2xs text-gray-400 mt-0.5">${escape(a.rule_triggered || '—')} · ${fmtDate(a.fired_at)}</div>
              </div>
              <div class="text-2xs text-gray-400 tabular-nums shrink-0 self-center">${fmtDate(a.fired_at)}</div>
            </div>`).join('')}
          </div>
        </section>`).join('')}
    </div>
  `;
}

// ============== 3. Rankings ==============
function renderRankings() {
  const us = DATA.rank.filter(r => r.region_code === 'us' && r.source === 'sensor_tower');
  const af = us.find(r => r.competitor === BASELINE);
  const others = us.filter(r => r.competitor && r.competitor !== BASELINE)
    .sort((a,b) => (a.rank_value ?? 999) - (b.rank_value ?? 999));
  const movers = us.filter(r => r.delta != null && Math.abs(r.delta) >= 5).length;
  const top50 = us.filter(r => r.rank_value != null && r.rank_value <= 50).length;
  const tracked = new Set(us.map(r => r.competitor)).size;

  const renderDelta = (d) => {
    if (d == null) return '<span class="text-gray-400">—</span>';
    if (d === 0) return '<span class="text-gray-400">—</span>';
    const up = d > 0;
    return `<span class="${up ? 'text-success' : 'text-danger'} tabular-nums">${up ? '↑' : '↓'} ${Math.abs(d)}</span>`;
  };
  const renderVs = (rank, afRank) => {
    if (rank == null || afRank == null) return '<span class="text-gray-400">—</span>';
    const d = afRank - rank;
    if (d === 0) return '<span class="text-gray-400">0 名</span>';
    const cls = d > 0 ? 'text-danger' : 'text-success';
    return `<span class="${cls} tabular-nums">${d > 0 ? '+' : ''}${d} 名</span>`;
  };

  return `${pageHeader("排名异动", "美区 sensor_tower 数据 · AllFootball 蓝色行 = baseline")}
    ${kpiRow([
      kpi("追踪 app 数", tracked),
      kpi("24h 异动 ≥5", movers, "rank 变 ≥ 5 名"),
      kpi("进 Top 50", top50),
      kpi("数据源", "sensor_tower", "美区"),
    ])}
    <div class="border border-gray-200 rounded-md bg-white overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-gray-50 text-2xs uppercase tracking-wider text-gray-400">
          <tr><th class="text-left px-3 h-8">产品</th><th class="text-right px-3 h-8">当前排名</th><th class="text-right px-3 h-8">24h 变化</th><th class="text-right px-3 h-8">下载估算</th><th class="text-right px-3 h-8">vs AF</th></tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          ${af ? `<tr class="row-baseline font-medium">
            <td class="px-3 h-9"><span class="text-info">${BASELINE}</span><span class="ml-2 text-2xs text-info">[baseline]</span></td>
            <td class="px-3 h-9 text-right tabular-nums">${af.rank_value != null ? '#' + af.rank_value : '—'}</td>
            <td class="px-3 h-9 text-right">${renderDelta(af.delta)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${escape(af.downloads || '—')}</td>
            <td class="px-3 h-9 text-right text-gray-400">—</td>
          </tr>` : ''}
          ${others.map(r => `<tr>
            <td class="px-3 h-9 font-medium">${escape(r.competitor)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${r.rank_value != null ? '#' + r.rank_value : '—'}</td>
            <td class="px-3 h-9 text-right">${renderDelta(r.delta)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${escape(r.downloads || '—')}</td>
            <td class="px-3 h-9 text-right">${renderVs(r.rank_value, af ? af.rank_value : null)}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;
}

// ============== 4. Revenue ==============
function renderRevenue() {
  const us = DATA.rank.filter(r => r.region_code === 'us' && r.source === 'sensor_tower');
  const af = us.find(r => r.competitor === BASELINE);
  const others = us.filter(r => r.competitor && r.competitor !== BASELINE)
    .sort((a,b) => (b.revenue_num||0) - (a.revenue_num||0));

  const vs = (val, base) => {
    if (val == null || !base) return '<span class="text-gray-400">—</span>';
    const d = (val - base) / base;
    const cls = d > 0 ? 'text-danger' : 'text-success';
    return `<span class="${cls} tabular-nums">${d > 0 ? '+' : ''}${(d*100).toFixed(1)}%</span>`;
  };

  return `${pageHeader("收入下载", "以 AF 为基准对比所有竞品（数据源：Sensor Tower 月估算）")}
    ${kpiRow([
      kpi("AF 月下载", af ? fmtNum(af.downloads_num) : '—', "美区"),
      kpi("AF 月收入", af && af.revenue_num ? '$' + fmtNum(af.revenue_num) : '—', "美区"),
      kpi("AF 排名", af && af.rank_value ? '#' + af.rank_value : '—', "体育榜"),
      kpi("数据完整度", `${others.filter(r => r.revenue_num != null).length}/${others.length}`, "竞品有收入数据的"),
    ])}
    <div class="border border-gray-200 rounded-md bg-white overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-gray-50 text-2xs uppercase tracking-wider text-gray-400">
          <tr><th class="text-left px-3 h-8">产品</th><th class="text-right px-3 h-8">月下载</th><th class="text-right px-3 h-8">vs AF</th><th class="text-right px-3 h-8">月收入</th><th class="text-right px-3 h-8">vs AF</th><th class="text-right px-3 h-8">排名</th></tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          ${af ? `<tr class="row-baseline font-medium">
            <td class="px-3 h-9"><span class="text-info">${BASELINE}</span><span class="ml-2 text-2xs text-info">[baseline]</span></td>
            <td class="px-3 h-9 text-right tabular-nums">${fmtNum(af.downloads_num)}</td>
            <td class="px-3 h-9 text-right text-gray-400">—</td>
            <td class="px-3 h-9 text-right tabular-nums">$${fmtNum(af.revenue_num)}</td>
            <td class="px-3 h-9 text-right text-gray-400">—</td>
            <td class="px-3 h-9 text-right tabular-nums">#${af.rank_value || '—'}</td>
          </tr>` : ''}
          ${others.map(r => `<tr>
            <td class="px-3 h-9 font-medium">${escape(r.competitor)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${fmtNum(r.downloads_num)}</td>
            <td class="px-3 h-9 text-right">${vs(r.downloads_num, af && af.downloads_num)}</td>
            <td class="px-3 h-9 text-right tabular-nums">$${fmtNum(r.revenue_num)}</td>
            <td class="px-3 h-9 text-right">${vs(r.revenue_num, af && af.revenue_num)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${r.rank_value ? '#' + r.rank_value : '—'}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;
}

// ============== 5. IAP ==============
function renderIap() {
  const all = DATA.iap.filter(it => COMPETITORS.includes(it.competitor));
  const grouped = {};
  all.forEach(it => {
    if (!grouped[it.competitor]) grouped[it.competitor] = {};
    if (!grouped[it.competitor][it.name]) grouped[it.competitor][it.name] = [];
    grouped[it.competitor][it.name].push(it);
  });
  let totalIap = 0;
  Object.values(grouped).forEach(g => { totalIap += Object.keys(g).length; });

  return `${pageHeader("IAP 内购", "9 竞品的 IAP 商品配置（按 spec 不展示 AllFootball）")}
    ${kpiRow([
      kpi("覆盖竞品", Object.keys(grouped).length),
      kpi("IAP 总数", totalIap, "去重后"),
      kpi("覆盖区域", new Set(all.map(it => it.region_code)).size),
      kpi("价格记录", all.length, "原始行数"),
    ])}
    <div class="space-y-3">
      ${Object.entries(grouped).map(([app, items]) => `
        <section class="border border-gray-200 rounded-md bg-white">
          <header class="flex items-center justify-between px-3 h-9 bg-gray-50 border-b border-gray-100">
            <span class="text-sm font-medium">${escape(app)}</span>
            <span class="text-2xs text-gray-400">${Object.keys(items).length} 个 IAP</span>
          </header>
          <table class="w-full text-xs">
            <thead class="text-2xs uppercase tracking-wider text-gray-400">
              <tr><th class="text-left px-3 py-1.5">名称</th><th class="text-left px-3 py-1.5">类型</th><th class="text-left px-3 py-1.5">区域 × 价格</th></tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              ${Object.entries(items).map(([name, regions]) => {
                const sample = regions[0];
                return `<tr><td class="px-3 py-2 align-top font-medium">${escape(name)}</td><td class="px-3 py-2 align-top text-gray-400">${escape(sample.category||'—')}</td><td class="px-3 py-2 align-top"><div class="flex flex-wrap gap-1">${regions.map(r => `<span class="inline-flex items-center gap-1 px-1.5 h-5 rounded bg-gray-50 text-2xs font-mono"><span class="uppercase text-gray-400">${escape(r.region_code)}</span><span class="tabular-nums">${escape(r.price||'—')}</span></span>`).join('')}</div></td></tr>`;
              }).join('')}
            </tbody>
          </table>
        </section>`).join('')}
    </div>`;
}

// ============== 6. Website ==============
function renderWebsite() {
  const af = DATA.website.find(w => w.competitor === BASELINE);
  const others = DATA.website.filter(w => w.competitor !== BASELINE)
    .sort((a,b) => (b.monthly_visits_num||0) - (a.monthly_visits_num||0));
  const vs = (val, base) => {
    if (val == null || !base) return '<span class="text-gray-400">—</span>';
    const d = (val - base) / base;
    return `<span class="${d > 0 ? 'text-danger' : 'text-success'} tabular-nums">${d > 0 ? '+' : ''}${(d*100).toFixed(1)}%</span>`;
  };
  return `${pageHeader("网站数据", "Similarweb · device split / 6 渠道分布 / top_keywords 已永久删除（trial-only）")}
    ${kpiRow([
      kpi("AF 月访问", af ? af.monthly_visits : '—', "本月"),
      kpi("AF 平均停留", af ? af.avg_visit_duration : '—'),
      kpi("AF 跳出率", af ? fmtPct(af.bounce_rate) : '—'),
      kpi("AF 全球排名", af && af.global_rank ? '#' + af.global_rank.toLocaleString() : '—', af ? `主要 ${af.country_rank_country}` : ''),
    ])}
    <div class="border border-gray-200 rounded-md bg-white overflow-hidden mb-4">
      <table class="w-full text-xs">
        <thead class="bg-gray-50 text-2xs uppercase tracking-wider text-gray-400">
          <tr><th class="text-left px-3 h-8">产品</th><th class="text-right px-3 h-8">月访问</th><th class="text-right px-3 h-8">vs AF</th><th class="text-right px-3 h-8">平均停留</th><th class="text-right px-3 h-8">页/访问</th><th class="text-right px-3 h-8">跳出率</th><th class="text-right px-3 h-8">全球排名</th></tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          ${af ? `<tr class="row-baseline font-medium">
            <td class="px-3 h-9"><span class="text-info">${BASELINE}</span><span class="ml-2 text-2xs text-info">[baseline]</span></td>
            <td class="px-3 h-9 text-right tabular-nums">${escape(af.monthly_visits)}</td>
            <td class="px-3 h-9 text-right text-gray-400">—</td>
            <td class="px-3 h-9 text-right tabular-nums">${escape(af.avg_visit_duration)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${(af.pages_per_visit||0).toFixed(2)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${fmtPct(af.bounce_rate)}</td>
            <td class="px-3 h-9 text-right tabular-nums">#${af.global_rank ? af.global_rank.toLocaleString() : '—'}</td>
          </tr>` : ''}
          ${others.map(r => `<tr>
            <td class="px-3 h-9 font-medium">${escape(r.competitor)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${escape(r.monthly_visits || '—')}</td>
            <td class="px-3 h-9 text-right">${vs(r.monthly_visits_num, af && af.monthly_visits_num)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${escape(r.avg_visit_duration || '—')}</td>
            <td class="px-3 h-9 text-right tabular-nums">${(r.pages_per_visit||0).toFixed(2)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${fmtPct(r.bounce_rate)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${r.global_rank ? '#' + r.global_rank.toLocaleString() : '—'}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="grid grid-cols-2 gap-3">
      <section class="border border-gray-200 rounded-md bg-white"><header class="px-3 h-8 bg-gray-50 border-b border-gray-100 flex items-center"><span class="text-sm font-medium">Top Countries</span></header><div class="p-3 text-xs space-y-2">${DATA.website.filter(r => r.top_countries && r.top_countries.length).slice(0, 5).map(r => `<div><div class="font-medium mb-1">${escape(r.competitor)}</div><div class="flex flex-wrap gap-1">${r.top_countries.slice(0,5).map(c => `<span class="px-1.5 h-5 inline-flex items-center gap-1 rounded bg-gray-50 text-2xs"><span>${escape(c.country)}</span><span class="tabular-nums text-gray-400">${fmtPct(c.share)}</span></span>`).join('')}</div></div>`).join('')}</div></section>
      <section class="border border-gray-200 rounded-md bg-white"><header class="px-3 h-8 bg-gray-50 border-b border-gray-100 flex items-center"><span class="text-sm font-medium">Similar Sites</span></header><div class="p-3 text-xs space-y-2">${DATA.website.filter(r => r.similar_sites && r.similar_sites.length).slice(0, 5).map(r => `<div><div class="font-medium mb-1">${escape(r.competitor)}</div><div class="flex flex-wrap gap-1">${r.similar_sites.slice(0,6).map(s => `<span class="px-1.5 h-5 inline-flex items-center gap-1 rounded bg-gray-50 text-2xs"><span class="font-mono">${escape(s.domain)}</span><span class="tabular-nums text-gray-400">${fmtPct(s.affinity)}</span></span>`).join('')}</div></div>`).join('')}</div></section>
    </div>
  `;
}

// ============== 7. Releases ==============
function renderReleases() {
  const all = DATA.alerts.filter(a => a.alert_type === 'release');
  const byApp = {};
  all.forEach(a => { (byApp[a.app_name] = byApp[a.app_name] || []).push(a); });
  return `${pageHeader("产品动态", "竞品版本发布节奏（来自 reviews.version 字段）")}
    ${kpiRow([
      kpi("发版总数", all.length, "30d"),
      kpi("覆盖 app", Object.keys(byApp).length),
      kpi("本地化迹象", "—"),
      kpi("发版冠军", Object.entries(byApp).sort((a,b)=>b[1].length-a[1].length)[0]?.[0] || '—'),
    ])}
    <div class="space-y-3">
      ${Object.entries(byApp).map(([app, list]) => `
        <section class="border border-gray-200 rounded-md bg-white overflow-hidden">
          <header class="flex items-center justify-between px-3 h-9 bg-gray-50 border-b border-gray-100">
            <span class="text-sm font-medium">${escape(app)}</span>
            <span class="text-2xs text-gray-400">${list.length} 次发版</span>
          </header>
          <div class="divide-y divide-gray-100">
            ${list.map(a => {
              const md = a.metadata || {};
              return `<div class="px-3 py-2 text-xs"><div class="flex items-baseline gap-2"><span class="font-mono font-medium">${escape(md.version || '—')}</span><span class="text-2xs text-gray-400 tabular-nums">${md.first_seen ? fmtDateOnly(md.first_seen) : '—'}</span>${md.obs_count != null ? `<span class="text-2xs text-gray-400 tabular-nums ml-auto">${md.obs_count} 次观测</span>` : ''}</div>${a.title ? `<div class="mt-0.5 text-gray-400 line-clamp-2">${escape(a.title)}</div>` : ''}</div>`;
            }).join('')}
          </div>
        </section>`).join('')}
    </div>
  `;
}

// ============== 8. GP Reviews（6×9 矩阵 + 评论流）==============
function renderReviews() {
  const labels = ["complaint","feature_request","competitor_compare","churn_signal","positive","other"];
  const matrix = {};
  COMPETITORS.forEach(c => matrix[c] = { complaint:0, feature_request:0, competitor_compare:0, churn_signal:0, positive:0, other:0 });
  DATA.reviews.forEach(r => {
    if (r.label && matrix[r.competitor]) matrix[r.competitor][r.label]++;
  });

  const total = DATA.reviews.length;
  const counts = labels.reduce((a, l) => { a[l] = DATA.reviews.filter(r => r.label === l).length; return a; }, {});

  return `${pageHeader("GP 评论", "6 类标签矩阵 + 评论原文 + 实体抽取")}
    ${kpiRow([
      kpi("总评论数", total, "已 AI 标"),
      kpi("高价值请求", counts.feature_request),
      kpi("问题抱怨", counts.complaint),
      kpi("流失信号", counts.churn_signal),
    ])}
    <div class="border border-gray-200 rounded-md bg-white overflow-hidden mb-4">
      <header class="px-3 h-9 bg-gray-50 border-b border-gray-100 flex items-center"><span class="text-sm font-medium">6 类标签矩阵</span><span class="ml-2 text-2xs text-gray-400">9 行 × 6 列</span></header>
      <table class="w-full text-xs">
        <thead class="text-2xs text-gray-400"><tr><th class="text-left px-3 py-1.5">竞品</th>${labels.map(l => `<th class="text-right px-3 py-1.5">${LABEL_DISPLAY[l].text}</th>`).join('')}</tr></thead>
        <tbody class="divide-y divide-gray-100">
          ${COMPETITORS.map(app => `<tr>
            <td class="px-3 py-1.5 font-medium">${escape(app)}</td>
            ${labels.map(l => {
              const n = matrix[app][l];
              return `<td class="text-right px-3 py-1.5 tabular-nums ${n === 0 ? 'text-gray-300' : ''}">${n}</td>`;
            }).join('')}
          </tr>`).join('')}
        </tbody>
      </table>
    </div>

    <div class="border border-gray-200 rounded-md bg-white overflow-hidden">
      <header class="px-3 h-9 bg-gray-50 border-b border-gray-100 flex items-center justify-between"><span class="text-sm font-medium">最近 30 条评论</span><span class="text-2xs text-gray-400">${total} 总数</span></header>
      <div class="divide-y divide-gray-100">
        ${DATA.reviews.slice(0, 30).map(r => {
          const ld = LABEL_DISPLAY[r.label] || LABEL_DISPLAY.other;
          return `<article class="px-3 py-2.5 text-xs">
            <div class="flex items-baseline gap-2 flex-wrap mb-1">
              <span class="font-medium">${escape(r.competitor)}</span>
              <span class="text-2xs text-gray-400 font-mono uppercase">${escape(r.region_code)}</span>
              ${r.score != null ? `<span class="text-2xs text-gray-400">${r.score}★</span>` : ''}
              ${r.version ? `<span class="text-2xs font-mono text-gray-400">${escape(r.version)}</span>` : ''}
              ${pill(ld.text, ld.pill)}
              <span class="ml-auto text-2xs text-gray-400 tabular-nums">${fmtDateOnly(r.at)}</span>
            </div>
            <div class="leading-snug">${escape((r.translated_text || r.content || '').slice(0, 400))}</div>
            ${r.entities && r.entities.length ? `<div class="mt-1.5 flex flex-wrap gap-1">${r.entities.map(e => `<span class="text-2xs px-1.5 h-5 inline-flex items-center rounded bg-gray-50 font-mono" title="${escape(e.canonical_id)}">${escape(e.raw_value)}</span>`).join('')}</div>` : ''}
          </article>`;
        }).join('')}
      </div>
    </div>
  `;
}

// ============== 9. Social ==============
function renderSocial() {
  const all = DATA.community;
  const reddit = all.filter(p => p.source === 'reddit').length;
  const twitter = all.filter(p => p.source === 'twitter').length;
  const hot = all.filter(p => (p.score||0) >= 100).length;
  return `${pageHeader("社媒评论", "Reddit + Twitter 帖子（按热度排序）")}
    ${kpiRow([
      kpi("总帖子数", all.length),
      kpi("Reddit", reddit),
      kpi("Twitter", twitter, "fapi.uk 待付费"),
      kpi("高热（≥100）", hot),
    ])}
    <div class="border border-gray-200 rounded-md bg-white divide-y divide-gray-100">
      ${all.slice(0, 50).map(p => `<article class="px-3 py-3">
        <div class="flex items-baseline gap-2 mb-1 flex-wrap">
          <span class="text-xs font-medium">${escape(p.competitor)}</span>
          <span class="text-2xs px-1 rounded font-mono bg-gray-50 text-gray-400 uppercase">${escape(p.source)}</span>
          ${p.subreddit ? `<span class="text-2xs text-gray-400 font-mono">r/${escape(p.subreddit)}</span>` : ''}
          <span class="ml-auto inline-flex gap-3 text-2xs text-gray-400 tabular-nums">
            <span>↑ ${p.score || 0}</span><span>💬 ${p.num_comments || 0}</span>${p.created_utc ? `<span>${fmtDateOnly(p.created_utc)}</span>` : ''}
          </span>
        </div>
        <a href="${escape(p.url || '#')}" target="_blank" class="text-sm font-medium hover:text-brand-700">${escape(p.title || '(无标题)')}</a>
        ${p.selftext ? `<p class="mt-1 text-xs text-gray-500 line-clamp-3 leading-snug">${escape(p.selftext.slice(0, 300))}</p>` : ''}
      </article>`).join('')}
    </div>
  `;
}

// ============== 10. News ==============
function renderNews() {
  const all = DATA.news;
  const counts = { partnership: 0, acquires: 0, funding: 0 };
  all.forEach(n => {
    const t = `${n.title || ''} ${n.desc || ''}`.toLowerCase();
    Object.keys(counts).forEach(k => { if (t.includes(k)) counts[k]++; });
  });
  return `${pageHeader("商业新闻", "Google News RSS · 命中 business 关键词的事件")}
    ${kpiRow([
      kpi("新闻数", all.length, "近 7d"),
      kpi("partnership", counts.partnership, "合作 / 联营"),
      kpi("acquires", counts.acquires, "收并购"),
      kpi("funding", counts.funding, "融资"),
    ])}
    <div class="border border-gray-200 rounded-md bg-white divide-y divide-gray-100">
      ${all.slice(0, 30).map(n => `<article class="px-3 py-2.5">
        <div class="flex items-baseline gap-2 mb-1">
          <span class="text-xs font-medium">${escape(n.competitor)}</span>
          <span class="text-2xs text-gray-400">${escape(n.source || '')}</span>
          ${n.is_biz ? '<span class="text-2xs px-1 rounded bg-pill-amber">⭐ biz</span>' : ''}
          <span class="ml-auto text-2xs text-gray-400 tabular-nums">${n.pub_iso ? new Date(n.pub_iso).toLocaleDateString('zh-CN') : '—'}</span>
        </div>
        <a href="${escape(n.link || '#')}" target="_blank" class="text-sm font-medium hover:text-brand-700">${escape(n.title || '')}</a>
        ${n.desc ? `<p class="mt-1 text-xs text-gray-400 line-clamp-2 leading-snug">${escape(n.desc)}</p>` : ''}
      </article>`).join('')}
    </div>
  `;
}

// ============== 11. Ads ==============
function renderAds() {
  const matrix = {};
  DATA.ads.forEach(ad => {
    if (!matrix[ad.competitor]) matrix[ad.competitor] = {};
    if (!matrix[ad.competitor][ad.region]) matrix[ad.competitor][ad.region] = [];
    matrix[ad.competitor][ad.region].push(ad);
  });
  return `${pageHeader("广告投放", "Meta 广告库 · 竞品 × 国家矩阵")}
    ${kpiRow([
      kpi("活跃创意", DATA.ads.length),
      kpi("覆盖竞品", Object.keys(matrix).length),
      kpi("覆盖国家", new Set(DATA.ads.map(a => a.region)).size),
      kpi("Top1 国家", "us"),
    ])}
    <div class="space-y-2">
      ${Object.entries(matrix).map(([app, regions]) => {
        const total = Object.values(regions).reduce((s, x) => s + x.length, 0);
        return `<section class="border border-gray-200 rounded-md bg-white">
          <header class="flex items-center justify-between px-3 h-9 bg-gray-50 border-b border-gray-100">
            <span class="text-sm font-medium">${escape(app)}</span>
            <span class="text-2xs text-gray-400">${total} 创意 · ${Object.keys(regions).length} 国</span>
          </header>
          <div class="grid grid-cols-2 divide-x divide-gray-100">
            ${Object.entries(regions).slice(0,2).map(([region, ads]) => `<div class="p-3 space-y-2">
              <div class="text-2xs uppercase font-mono text-gray-400">${REGION_LABEL[region]||region.toUpperCase()} · ${ads.length}</div>
              ${ads.slice(0, 3).map(ad => `<div class="text-xs text-gray-500 line-clamp-3 leading-snug border-l-2 border-gray-200 pl-2">${escape(ad.body_text || '(无文案)')}</div>`).join('')}
            </div>`).join('')}
          </div>
        </section>`;
      }).join('')}
    </div>
  `;
}

// ============== 12. Candidates ==============
function renderCandidates() {
  const all = DATA.candidates;
  return `${pageHeader("候选发现", "AI 分类的潜在新竞品 · candidate 永远不会自动写入 competitors")}
    ${kpiRow([
      kpi("本周新增", all.length, "符合门槛"),
      kpi("待审阅", all.length),
      kpi("已采纳", 0),
      kpi("已拒绝", 0),
    ])}
    <div class="px-3 py-2 mb-3 text-2xs text-gray-500 bg-pill-amber rounded">审阅状态仅本地存储。采纳后请把 JSON 片段贴入 <code class="font-mono">data/competitors.json</code>。</div>
    <div class="border border-gray-200 rounded-md bg-white overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-gray-50 text-2xs uppercase tracking-wider text-gray-400">
          <tr><th class="text-left px-3 h-8">App</th><th class="text-left px-3 h-8">发行商</th><th class="text-left px-3 h-8">topic</th><th class="text-left px-3 h-8">categories</th><th class="text-right px-3 h-8">conf</th></tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          ${all.map(c => `<tr>
            <td class="px-3 h-9"><div class="font-medium">${escape(c.name)}</div><div class="text-2xs text-gray-400 font-mono">${escape(c.platform)}:${escape(c.app_id)}</div></td>
            <td class="px-3 h-9 text-gray-400">${escape(c.publisher || '—')}</td>
            <td class="px-3 h-9">${pill(TOPIC_LABEL[c.topic]||c.topic, "bg-pill-blue")}</td>
            <td class="px-3 h-9"><div class="flex gap-1 flex-wrap">${(c.categories||[]).slice(0,4).map(cat => pill(CAT_LABEL[cat]||cat, "bg-pill-gray")).join('')}</div></td>
            <td class="px-3 h-9 text-right tabular-nums font-mono">${c.confidence.toFixed(2)}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;
}

// ============== 13. Failed AI Jobs ==============
function renderFailed() {
  const all = DATA.failed_ai_jobs;
  return `${pageHeader("AI 失败队列", "重试耗尽的 AI 任务（4 个 task × 4 种 error_kind）")}
    ${kpiRow([
      kpi("未解决总数", all.filter(j => !j.resolved_at).length),
      kpi("comment_label", all.filter(j => j.task_name === 'comment_label').length),
      kpi("entity_extract", all.filter(j => j.task_name === 'entity_extract').length),
      kpi("其他", all.filter(j => !['comment_label','entity_extract'].includes(j.task_name)).length),
    ])}
    ${all.length === 0 ? emptyHint("无失败任务（恭喜）") :
      `<div class="border border-gray-200 rounded-md bg-white overflow-hidden">
        <table class="w-full text-xs">
          <thead class="bg-gray-50 text-2xs uppercase tracking-wider text-gray-400">
            <tr><th class="text-left px-3 h-8">task</th><th class="text-left px-3 h-8">error_kind</th><th class="text-left px-3 h-8">error_msg</th><th class="text-right px-3 h-8">尝试</th><th class="text-right px-3 h-8">最近尝试</th></tr>
          </thead>
          <tbody class="divide-y divide-gray-100">
            ${all.map(j => `<tr>
              <td class="px-3 h-9 font-mono">${escape(j.task_name)}</td>
              <td class="px-3 h-9">${j.error_kind ? pill(j.error_kind, 'bg-pill-red') : '—'}</td>
              <td class="px-3 h-9 text-gray-400 truncate max-w-md">${escape((j.error_msg||'').slice(0, 80))}</td>
              <td class="px-3 h-9 text-right tabular-nums">${j.attempts}</td>
              <td class="px-3 h-9 text-right tabular-nums text-gray-400">${fmtDate(j.last_attempt_at)}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`
    }
  `;
}

// ============== 14. Sync Log ==============
function renderSync() {
  const all = DATA.sync_log;
  const ok = all.filter(l => l.success).length;
  const successRate = all.length ? `${((ok/all.length)*100).toFixed(0)}%` : '—';
  const lastOk = all.find(l => l.success);
  const avgDur = all.length ? (all.reduce((s,l) => s + (l.duration_sec||0), 0) / all.length).toFixed(1) + 's' : '—';
  return `${pageHeader("同步日志", "抓取作业详细日志（rolling 50 · 30s 自动刷新）")}
    ${kpiRow([
      kpi("近 50 次成功率", successRate),
      kpi("最近成功", lastOk ? fmtDate(lastOk.started_at) : '—'),
      kpi("retry queue", DATA.status.retry_queue_size, "待重跑"),
      kpi("平均耗时", avgDur),
    ])}
    <div class="border border-gray-200 rounded-md bg-white overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-gray-50 text-2xs uppercase tracking-wider text-gray-400">
          <tr><th class="text-left px-3 h-8">source</th><th class="text-left px-3 h-8">started_at</th><th class="text-right px-3 h-8">duration</th><th class="text-left px-3 h-8">状态</th><th class="text-left px-3 h-8">错误</th></tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          ${all.map(l => `<tr class="${!l.success ? 'bg-pill-red/30' : ''}">
            <td class="px-3 h-9 font-mono">${escape(l.script)}</td>
            <td class="px-3 h-9 tabular-nums text-gray-400">${fmtDate(l.started_at)}</td>
            <td class="px-3 h-9 text-right tabular-nums">${l.duration_sec != null ? l.duration_sec.toFixed(1) + 's' : '—'}</td>
            <td class="px-3 h-9">${l.success ? pill('成功','bg-pill-green') : pill(l.error_kind || '失败', 'bg-pill-red')}</td>
            <td class="px-3 h-9 text-gray-400 truncate max-w-md">${escape((l.stderr_tail||'').slice(0, 80))}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;
}
</script>
</body>
</html>
"""


def main():
    print("[1/2] 从 MySQL 导出数据 ...")
    data = export_data()
    sizes = {k: len(v) if isinstance(v, list) else "n/a" for k, v in data.items()}
    print(f"      {sizes}")

    print("[2/2] 渲染 HTML ...")
    payload = json.dumps(data, ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__DATA__", payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"\n✓ 输出：{OUT}")
    print(f"  大小：{size_kb:.1f} KB")
    print(f"\n双击打开：")
    print(f"  open {OUT}")


if __name__ == "__main__":
    main()
