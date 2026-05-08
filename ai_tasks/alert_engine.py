"""alert_engine — 规则层 + AI 文案。

Spec: AI_tasks_spec_v1_1.md（任务 3 上层）

每日 02:30 跑一次（在 daily_sync 之后），扫各 fact 表找符合 7 类规则的事件：
  ranking    · 排名突变（7 天内 ↑/↓ ≥ 5 名）
  commercial · IAP 价格变动（涨跌 ≥ ±10% 且影响 ≥ 5 区）
  news       · Google News business keyword 命中
  release    · 新版本发布（version 字符串变化）
  rating     · 评分下跌（4 天内下跌 ≥ 0.3 星）
  churn      · churn_signal 标签占比上升（7 天 vs 上 7 天）
  ads        · 广告投放量变化（7 天 vs 上 7 天 ±50%）

每条匹配事件：
1. 规则层算出 metadata（结构化 dict）
2. 调 alert_title 任务生成 ≤50 字 title
3. 写入 alerts 表

CLI：
    python3 -m ai_tasks.alert_engine               # 跑全部 7 类
    python3 -m ai_tasks.alert_engine --type ranking # 只跑某一类
    python3 -m ai_tasks.alert_engine --dry-run     # 只打印不入库 / 不调 AI
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

from sqlalchemy import text  # noqa: E402

from shared import db as _db  # noqa: E402
from shared.dao import alerts as dao_alerts  # noqa: E402
from ai_tasks.alert_title import generate_title  # noqa: E402

log = logging.getLogger("alert_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s · %(message)s")

VALID_TYPES = ["ranking", "commercial", "news", "release", "rating", "churn", "ads"]


# ---- 规则 1: ranking ----------------------------------------------------------

def rule_ranking() -> list[dict]:
    """7 天内 rank 变动 ≥ 5 名（任意方向）。

    数据源：market_rank_snapshots（appstore_rank / appmagic / sensor_tower / androidrank）

    历史：原版规则用相邻 1 天 self-join，但实际 cron 频率非每日（手动周更），导致永远
    匹配不到相邻日。改成"取最新 snapshot vs ≤ 6 天前最近的 snapshot"，跟 Rankings 页
    KPI / 表格"周变化"列保持口径一致。

    匹配维度对齐 /api/rank：(source, name/competitor_id, platform, region_code) 四元组。
    platform / region_code 用 NULL-safe equality (<=>) 处理 appmagic global / 不区分
    平台的源。
    """
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        rows = s.execute(text("""
            SELECT t.competitor_id, c.name as app_name,
                   t.region_code, t.source, t.platform,
                   t.rank_value as new_rank,
                   t.snapshot_date as new_date,
                   (SELECT m2.rank_value FROM market_rank_snapshots m2
                    WHERE m2.competitor_id = t.competitor_id
                      AND m2.region_code <=> t.region_code
                      AND m2.platform    <=> t.platform
                      AND m2.source       = t.source
                      AND m2.snapshot_date <= DATE_SUB(t.snapshot_date, INTERVAL 6 DAY)
                    ORDER BY m2.snapshot_date DESC LIMIT 1) as old_rank
            FROM market_rank_snapshots t
            JOIN competitors c ON c.id = t.competitor_id
            WHERE t.snapshot_date = (
                SELECT MAX(m3.snapshot_date) FROM market_rank_snapshots m3
                WHERE m3.competitor_id = t.competitor_id
                  AND m3.region_code <=> t.region_code
                  AND m3.platform    <=> t.platform
                  AND m3.source       = t.source
            )
              AND t.rank_value IS NOT NULL
              AND t.snapshot_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            HAVING old_rank IS NOT NULL
               AND ABS(new_rank - old_rank) >= 5
        """)).fetchall()
        for r in rows:
            change = int(r.old_rank - r.new_rank)   # 正数 = ↑（数字下降 = 排名上升）
            severity = "high" if abs(change) >= 10 else "mid"
            out.append({
                "alert_type": "ranking",
                "severity": severity,
                "app_name": r.app_name,
                "metadata": {
                    "region": r.region_code or "global",
                    "source": r.source,
                    "platform": r.platform,
                    "old_rank": int(r.old_rank),
                    "new_rank": int(r.new_rank),
                    "change": change,
                    "rule_triggered": "rank_delta_5plus_7d",
                },
                "rule_triggered": "rank_delta_5plus_7d",
            })
    return out


# ---- 规则 2: commercial -------------------------------------------------------

def rule_commercial() -> list[dict]:
    """同一 IAP 价格变动 ≥ ±10% 且影响 ≥ 5 区（同周抓取）。

    数据源：iap_items（按 competitor + name 跨 region 比对最新两次抓取）
    """
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        # Step 1: 拿出最近的 (app, iap_name) 对应的 region 级最新两次抓取价格
        rows = s.execute(text("""
            SELECT i1.competitor_id, c.name as app_name,
                   i1.region_code, i1.name as iap_name,
                   i1.price_num as new_price,
                   i2.price_num as old_price
            FROM iap_items i1
            JOIN competitors c ON c.id = i1.competitor_id
            JOIN iap_items i2
              ON i2.competitor_id = i1.competitor_id
             AND i2.region_code   = i1.region_code
             AND i2.name          = i1.name
             AND i2.fetched_at < DATE_SUB(NOW(), INTERVAL 1 DAY)
             AND i2.fetched_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            WHERE i1.fetched_at = (
                SELECT MAX(fetched_at) FROM iap_items
                WHERE competitor_id = i1.competitor_id
                  AND region_code   = i1.region_code
                  AND name          = i1.name
            )
              AND i2.fetched_at = (
                SELECT MAX(fetched_at) FROM iap_items
                WHERE competitor_id = i1.competitor_id
                  AND region_code   = i1.region_code
                  AND name          = i1.name
                  AND fetched_at < DATE_SUB(NOW(), INTERVAL 1 DAY)
              )
              AND i1.price_num IS NOT NULL
              AND i2.price_num IS NOT NULL
              AND i2.price_num > 0
              AND ABS(i1.price_num - i2.price_num) / i2.price_num >= 0.10
        """)).fetchall()
    # 后处理：按 (app, iap_name) 聚合，统计影响 region 数
    by_iap: dict[tuple, dict] = {}
    for r in rows:
        key = (r.app_name, r.iap_name)
        slot = by_iap.setdefault(key, {
            "app_name": r.app_name,
            "iap_name": r.iap_name,
            "regions": set(),
            "old": float(r.old_price),
            "new": float(r.new_price),
        })
        slot["regions"].add(r.region_code)
    for (app, iap_name), s in by_iap.items():
        if len(s["regions"]) < 5:
            continue
        old, new = s["old"], s["new"]
        pct = (new - old) / old * 100.0 if old else 0
        severity = "high" if abs(pct) >= 30 else "mid"
        out.append({
            "alert_type": "commercial",
            "severity": severity,
            "app_name": app,
            "metadata": {
                "iap_name": iap_name,
                "old_price_usd": old,
                "new_price_usd": new,
                "change_pct": round(pct, 1),
                "regions_count": len(s["regions"]),
                "rule_triggered": "iap_price_10pct_5regions",
            },
            "rule_triggered": "iap_price_10pct_5regions",
        })
    return out


# ---- 规则 3: news -------------------------------------------------------------

def rule_news() -> list[dict]:
    """Google News business keyword 命中（is_biz=true）当周。

    数据源：data/async_google_news.json（每周 RSS 抓取产物）
    去重：alerts 表里已发过的 (app, link) 直接跳过，避免重复入库。
    """
    p = _PROJECT_ROOT / "data" / "async_google_news.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    # 拉出 alerts 表里已存在的 news 链接（按 app + link）
    already: set[tuple[str, str]] = set()
    if _db.is_mysql_enabled():
        with _db.session() as s:
            rows = s.execute(text("""
                SELECT app_name,
                       JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.link')) AS link
                FROM alerts WHERE alert_type='news'
            """)).fetchall()
            already = {(r.app_name, r.link) for r in rows if r.link}
    out: list[dict] = []
    seen: set[tuple] = set()
    for rec in data:
        app = rec.get("competitor")
        items = (rec.get("data") or {}).get("items") or []
        for it in items:
            if not it.get("is_biz"):
                continue
            link = it.get("link") or ""
            key = (app, link)
            if key in seen or (app, link[:512]) in already:
                continue
            seen.add(key)
            out.append({
                "alert_type": "news",
                "severity": "mid",
                "app_name": app,
                "metadata": {
                    "headline": (it.get("title") or "")[:200],
                    "source": (it.get("source") or "")[:64],
                    "keyword_matched": "business_keyword",
                    "link": link[:512],
                },
                "rule_triggered": "google_news_biz_hit",
            })
    return out


# ---- 规则 4: release ----------------------------------------------------------

def rule_release() -> list[dict]:
    """同竞品同区在 7 天内出现新 version 字符串（之前没见过）。

    数据源：reviews 表 version 字段 — 评论里的 app version 暴露上线节奏
    去重：alerts 表里已发过的 (app, version) 直接跳过，避免重复入库。
    """
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        # 严格条件：每个 (app, version) 只取首次出现日 = 今日 - 14d 内 + 之前 60d 没见过 + obs ≥ 5
        # AND alerts 表里没发过同 (app, version)
        rows = s.execute(text("""
            SELECT c.name as app_name,
                   r.version,
                   COUNT(*) as obs_count,
                   MIN(r.fetched_at) as first_seen
            FROM reviews r
            JOIN competitors c ON c.id = r.competitor_id
            WHERE r.version IS NOT NULL
              AND r.version != ''
              AND r.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
              AND NOT EXISTS (
                SELECT 1 FROM reviews r2
                WHERE r2.competitor_id = r.competitor_id
                  AND r2.version = r.version
                  AND r2.fetched_at < DATE_SUB(NOW(), INTERVAL 14 DAY)
                  AND r2.fetched_at >= DATE_SUB(NOW(), INTERVAL 75 DAY)
              )
              AND NOT EXISTS (
                SELECT 1 FROM alerts a
                WHERE a.alert_type = 'release'
                  AND a.app_name = c.name
                  AND JSON_UNQUOTE(JSON_EXTRACT(a.metadata_json, '$.version')) = r.version
              )
            GROUP BY c.name, r.version
            HAVING COUNT(*) >= 5
            ORDER BY first_seen DESC
        """)).fetchall()
        # 同 app 同次扫描只发最新一个（最 fresh 的）— 旧版本的 release 报警价值低
        seen_app: set[str] = set()
        for r in rows:
            if r.app_name in seen_app:
                continue
            seen_app.add(r.app_name)
            out.append({
                "alert_type": "release",
                "severity": "low",
                "app_name": r.app_name,
                "metadata": {
                    "version": r.version,
                    "release_notes_excerpt": "",
                    "has_localization": False,
                    "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                    "obs_count": int(r.obs_count),
                },
                "rule_triggered": "new_version_in_reviews",
            })
    return out


# ---- 规则 5: rating -----------------------------------------------------------

def rule_rating() -> list[dict]:
    """4 天内某区评分均值下跌 ≥ 0.3 星。

    数据源：reviews.score（按 competitor + region）
    """
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        rows = s.execute(text("""
            SELECT c.name as app_name,
                   r.region_code,
                   AVG(CASE WHEN r.fetched_at >= DATE_SUB(NOW(), INTERVAL 4 DAY) THEN r.score END) as new_rating,
                   AVG(CASE WHEN r.fetched_at <  DATE_SUB(NOW(), INTERVAL 4 DAY)
                              AND r.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY) THEN r.score END) as old_rating,
                   COUNT(CASE WHEN r.fetched_at >= DATE_SUB(NOW(), INTERVAL 4 DAY) THEN 1 END) as new_n
            FROM reviews r
            JOIN competitors c ON c.id = r.competitor_id
            WHERE r.score IS NOT NULL
              AND r.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
            GROUP BY c.name, r.region_code
            HAVING new_rating IS NOT NULL AND old_rating IS NOT NULL
                AND new_n >= 10
                AND old_rating - new_rating >= 0.3
        """)).fetchall()
        for r in rows:
            severity = "high" if (r.old_rating - r.new_rating) >= 0.5 else "mid"
            out.append({
                "alert_type": "rating",
                "severity": severity,
                "app_name": r.app_name,
                "metadata": {
                    "region": r.region_code,
                    "old_rating": round(float(r.old_rating), 2),
                    "new_rating": round(float(r.new_rating), 2),
                    "days": 4,
                    "rule_triggered": "rating_drop_0_3_4d",
                },
                "rule_triggered": "rating_drop_0_3_4d",
            })
    return out


# ---- 规则 6: churn ------------------------------------------------------------

def rule_churn() -> list[dict]:
    """7 天 churn_signal 占比 vs 上 7 天 churn_signal 占比，上升 ≥ 50% 触发。

    数据源：reviews.label='churn_signal'
    """
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        rows = s.execute(text("""
            SELECT c.name as app_name,
                   SUM(CASE WHEN r.fetched_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                              AND r.label = 'churn_signal' THEN 1 ELSE 0 END) as new_churn,
                   SUM(CASE WHEN r.fetched_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                              AND r.labeled_at IS NOT NULL THEN 1 ELSE 0 END) as new_total,
                   SUM(CASE WHEN r.fetched_at <  DATE_SUB(NOW(), INTERVAL 7 DAY)
                              AND r.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
                              AND r.label = 'churn_signal' THEN 1 ELSE 0 END) as old_churn,
                   SUM(CASE WHEN r.fetched_at <  DATE_SUB(NOW(), INTERVAL 7 DAY)
                              AND r.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
                              AND r.labeled_at IS NOT NULL THEN 1 ELSE 0 END) as old_total
            FROM reviews r
            JOIN competitors c ON c.id = r.competitor_id
            WHERE r.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
            GROUP BY c.name
            HAVING new_total >= 20 AND old_total >= 20
        """)).fetchall()
        for r in rows:
            new_pct = (r.new_churn / r.new_total) if r.new_total else 0
            old_pct = (r.old_churn / r.old_total) if r.old_total else 0
            if old_pct == 0:
                continue
            ratio = new_pct / old_pct
            if ratio < 1.5:
                continue
            severity = "high" if ratio >= 2.0 else "mid"
            out.append({
                "alert_type": "churn",
                "severity": severity,
                "app_name": r.app_name,
                "metadata": {
                    "old_pct": round(old_pct * 100, 2),
                    "new_pct": round(new_pct * 100, 2),
                    "period_days": 7,
                    "ratio": round(ratio, 2),
                    "rule_triggered": "churn_pct_50pct_up_7d",
                },
                "rule_triggered": "churn_pct_50pct_up_7d",
            })
    return out


# ---- 规则 7: ads --------------------------------------------------------------

def rule_ads() -> list[dict]:
    """7 天 ads 总数 vs 上 7 天 ads 总数，变化 ≥ ±50%。

    数据源：ad_creatives 表（fb_adlib 抓取）
    """
    if not _db.is_mysql_enabled():
        return []
    out: list[dict] = []
    with _db.session() as s:
        rows = s.execute(text("""
            SELECT c.name as app_name,
                   SUM(CASE WHEN a.fetched_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) as new_count,
                   SUM(CASE WHEN a.fetched_at <  DATE_SUB(NOW(), INTERVAL 7 DAY)
                              AND a.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY) THEN 1 ELSE 0 END) as old_count,
                   COUNT(DISTINCT a.region_code) as regions_concentrated
            FROM ad_creatives a
            JOIN competitors c ON c.id = a.competitor_id
            WHERE a.fetched_at >= DATE_SUB(NOW(), INTERVAL 14 DAY)
            GROUP BY c.name
            HAVING (new_count >= 5 OR old_count >= 5)
        """)).fetchall()
        for r in rows:
            old = int(r.old_count or 0)
            new = int(r.new_count or 0)
            base = max(old, 1)
            ratio = new / base
            if 0.5 < ratio < 1.5:
                continue
            severity = "high" if ratio >= 3.0 or ratio <= 0.2 else "mid"
            out.append({
                "alert_type": "ads",
                "severity": severity,
                "app_name": r.app_name,
                "metadata": {
                    "count_old": old,
                    "count_new": new,
                    "period_days": 7,
                    "regions_concentrated": int(r.regions_concentrated or 0),
                    "rule_triggered": "ads_count_50pct_change_7d",
                },
                "rule_triggered": "ads_count_50pct_change_7d",
            })
    return out


# ---- 主流程 -------------------------------------------------------------------


RULES = {
    "ranking": rule_ranking,
    "commercial": rule_commercial,
    "news": rule_news,
    "release": rule_release,
    "rating": rule_rating,
    "churn": rule_churn,
    "ads": rule_ads,
}


def run_engine(*, types: list[str] | None = None, dry_run: bool = False) -> dict:
    types = types or VALID_TYPES
    summary = {"total_events": 0, "ai_titled": 0, "skipped_dup": 0,
               "by_type": {}}
    for t in types:
        rule_fn = RULES.get(t)
        if not rule_fn:
            continue
        try:
            events = rule_fn()
        except Exception as e:
            log.warning(f"rule_{t} failed: {e}")
            events = []
        log.info(f"rule {t}: {len(events)} events")
        summary["by_type"][t] = {"events": len(events), "alerts": 0}
        # news / release 类每条都是独立事件（headline / version 唯一），不去重
        # ranking / commercial / rating / churn / ads 类同竞品每天 1 次（用 fingerprint 去重）
        dedup_types = {"ranking", "commercial", "rating", "churn", "ads"}
        for ev in events:
            if ev["alert_type"] in dedup_types and dao_alerts.fingerprint_exists(
                alert_type=ev["alert_type"],
                app_name=ev.get("app_name") or "",
                metadata=ev.get("metadata") or {},
                days=1,
            ):
                summary["skipped_dup"] += 1
                continue
            if dry_run:
                log.info(f"  [dry] {ev['alert_type']} {ev['app_name']} "
                         f"severity={ev['severity']} metadata={ev['metadata']}")
                summary["total_events"] += 1
                continue
            # 写 alert（先无 title 写一行拿 id，再调 AI 回填 title）
            alert_id = dao_alerts.insert_alert(
                alert_type=ev["alert_type"],
                severity=ev.get("severity") or "mid",
                app_name=ev.get("app_name") or "",
                metadata=ev.get("metadata") or {},
                rule_triggered=ev.get("rule_triggered"),
            )
            summary["total_events"] += 1
            summary["by_type"][t]["alerts"] += 1
            if alert_id is None:
                continue
            try:
                title = generate_title(
                    alert_type=ev["alert_type"],
                    severity=ev.get("severity") or "mid",
                    app_name=ev.get("app_name") or "",
                    metadata=ev.get("metadata") or {},
                    alert_id=alert_id,
                )
                dao_alerts.set_title(alert_id, title)
                summary["ai_titled"] += 1
            except Exception as e:
                log.warning(f"alert_title failed for alert_id={alert_id}: {e}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=VALID_TYPES, action="append",
                    help="只跑指定 type（可重复）；不传 = 全部")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    summary = run_engine(types=args.type, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
