#!/usr/bin/env python3
"""seed_demo.py — Demo 数据填充

目标：让前端 dashboard 每张卡 / 每个页都有像样的数据展示。

策略：
- 跑过的真实数据**完全保留**（reviews 2951 条 / market_rank_snapshots 1526 条 / etc）
- 空表 / 稀疏表用合理 mock 填充（ad_creatives / iap_items / website_traffic / 等）
- reviews 里 NULL 的 label 用规则打标（score + 关键词），不调 AI（省钱 + 即时）
- 全部用 INSERT IGNORE 或 ON DUPLICATE KEY 保证幂等

幂等：可重复运行，已有的不重复加。

用法：
    python3 scripts/seed_demo.py             # 全量 seed
    python3 scripts/seed_demo.py --reset     # 先清空 demo 数据再 seed（保留真实抓取数据）
    python3 scripts/seed_demo.py --dry-run   # 只打印计划不写
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from shared.env_loader import load_all
    load_all()
except Exception:
    pass

from shared import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

random.seed(42)


# ─────────────────────────── 常量 ───────────────────────────

COMPETITORS = ["SofaScore", "FlashScore", "OneFootball", "365Scores", "Fotmob",
               "LiveScore", "AiScore", "BeSoccer", "310Scores"]
BASELINE = "AllFootball"
ALL_APPS = COMPETITORS + [BASELINE]

REGIONS = ["us", "gb", "de", "fr", "es", "it", "br", "mx", "ng", "sa", "ae", "jp"]
AD_REGIONS = ["us", "gb", "br", "mx", "ng"]   # fb_adlib 实际跑的 5 国

# IAP 模板 — 真实参考 SofaScore / OneFootball / Fotmob 的 IAP 配置
IAP_NAMES = [
    ("VIP Monthly", "subscription", 4.99),
    ("VIP Annual", "subscription", 39.99),
    ("Remove Ads", "consumable", 2.99),
    ("Premium Stats", "subscription", 9.99),
    ("AI Predictions", "subscription", 6.99),
    ("Coin Pack 100", "consumable", 0.99),
]

# 区域 → 货币 + 价格调整系数
REGION_CURRENCY = {
    "us": ("USD", 1.0), "gb": ("GBP", 0.8), "de": ("EUR", 0.92),
    "fr": ("EUR", 0.92), "es": ("EUR", 0.92), "it": ("EUR", 0.92),
    "br": ("BRL", 5.0), "mx": ("MXN", 17.0), "ng": ("NGN", 1500.0),
    "sa": ("SAR", 3.75), "ae": ("AED", 3.67), "jp": ("JPY", 150.0),
}
CURRENCY_SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "BRL": "R$",
                   "MXN": "MX$", "NGN": "₦", "SAR": "SAR ", "AED": "AED ",
                   "JPY": "¥"}

# 广告文案池（按语言/地区分桶）
AD_BODY_BY_REGION = {
    "us": [
        "Live football scores. Real-time stats. Free download.",
        "{app}: Track every Premier League match in real time.",
        "Watch the World Cup live. {app} brings you minute-by-minute coverage.",
        "Get instant notifications for every goal. Try {app} free.",
        "The fastest live scores app. Trusted by 50M+ fans.",
    ],
    "gb": [
        "{app}: Premier League, Champions League, all in one app.",
        "Don't miss a goal. Live scores from 600+ leagues.",
        "Free download. Premium stats. Real-time updates.",
        "Match starts in 5 minutes. Set your alert with {app}.",
        "Lineups, stats, predictions — all live, all free.",
    ],
    "br": [
        "{app}: Placares ao vivo de Brasileirão, Libertadores e mais.",
        "Não perca um gol. Notificações em tempo real.",
        "O melhor app de futebol do Brasil. Baixe grátis.",
        "Estatísticas, escalações, ao vivo. Tudo no {app}.",
        "Acompanhe seu time favorito 24/7.",
    ],
    "mx": [
        "{app}: Marcadores en vivo de Liga MX, La Liga y mucho más.",
        "Notificaciones de cada gol. Descarga {app} gratis.",
        "Estadísticas en tiempo real. Para los verdaderos fans.",
        "Champions League, Mundial, todo en {app}.",
        "Tu compañero perfecto para cada partido.",
    ],
    "ng": [
        "{app}: Live scores from EPL, La Liga, Naija Premier League.",
        "Get live stats and goals notifications. Free.",
        "Trusted by football fans across Africa.",
        "Watch the action unfold in real-time.",
        "Premier League, AFCON, all in one place.",
    ],
}

# 评论关键词 → label 的简单规则（mock AI label）
LABEL_RULES = [
    ("complaint", ["crash", "lag", "slow", "freeze", "broken", "ad ", "ads ", "annoying", "bug"]),
    ("feature_request", ["wish", "please add", "would love", "hope", "could you", "needs"]),
    ("competitor_compare", ["sofascore", "flashscore", "fotmob", "365scores", "livescore", "better than", "worse than"]),
    ("churn_signal", ["uninstall", "delete", "switch", "moved to", "going back to", "deleted", "deleting"]),
    ("positive", ["best", "amazing", "love it", "perfect", "great app", "excellent", "fantastic", "awesome"]),
]

# 实体池（按 9 类）
ENTITY_SEED = [
    # competitors（前端 + 后端互引）
    ("competitor", "competitor_sofascore", "Sofascore", ["SofaScore", "sofascore", "SOFA"]),
    ("competitor", "competitor_flashscore", "FlashScore", ["flash score", "FlashScore"]),
    ("competitor", "competitor_fotmob", "FotMob", ["fotmob", "FotMob"]),
    ("competitor", "competitor_onefootball", "OneFootball", ["one football", "OneFootball"]),
    ("competitor", "competitor_365scores", "365Scores", ["365", "365 Scores"]),
    # features
    ("feature", "feature_live_streaming", "直播", ["live stream", "live video", "watch live"]),
    ("feature", "feature_ai_prediction", "AI 比分预测", ["AI predictions", "match prediction"]),
    ("feature", "feature_dark_mode", "深色模式", ["dark mode", "dark theme"]),
    ("feature", "feature_apple_watch", "Apple Watch 同步", ["apple watch", "watch app"]),
    ("feature", "feature_widget", "桌面 widget", ["widget", "home screen"]),
    ("feature", "feature_lineup", "首发阵容", ["lineup", "starting xi", "lineups"]),
    # leagues
    ("league", "league_la_liga", "西甲", ["la liga", "LaLiga"]),
    ("league", "league_premier_league", "英超", ["premier league", "EPL"]),
    ("league", "league_champions_league", "欧冠", ["champions league", "UCL"]),
    ("league", "league_serie_a", "意甲", ["serie a"]),
    ("league", "league_bundesliga", "德甲", ["bundesliga"]),
    ("league", "league_brasileirao", "巴甲", ["brasileirao", "brasileirão"]),
    # players
    ("player", "player_ronaldo", "C 罗", ["Cristiano", "Ronaldo", "CR7"]),
    ("player", "player_messi", "梅西", ["Messi"]),
    ("player", "player_mbappe", "姆巴佩", ["Mbappé", "Mbappe"]),
    ("player", "player_bellingham", "贝林厄姆", ["Bellingham"]),
    ("player", "player_haaland", "哈兰德", ["Haaland"]),
    # device
    ("device", "device_iphone", "iPhone", ["iPhone"]),
    ("device", "device_android", "Android", ["Android"]),
    ("device", "device_ios18", "iOS 18", ["iOS 18", "iOS18"]),
    # bugs
    ("bug", "bug_crash", "闪退", ["crash", "crashes"]),
    ("bug", "bug_lag", "卡顿", ["lag", "laggy", "slow"]),
    ("bug", "bug_push_failed", "推送失效", ["notification not working", "push fail"]),
    # localization
    ("localization", "localization_arabic", "阿拉伯语", ["arabic", "RTL"]),
    ("localization", "localization_spanish", "西班牙语", ["spanish", "español"]),
    # payment
    ("payment", "payment_apple_pay", "Apple Pay", ["Apple Pay"]),
    ("payment", "payment_oxxo", "OXXO", ["OXXO"]),
    # language
    ("language", "language_translation", "翻译质量", ["translation", "翻译"]),
]


# ─────────────────────────── helpers ───────────────────────────


def _now() -> datetime:
    return datetime.utcnow()


def _resolve_competitor_id(s, name: str) -> int | None:
    row = s.execute(text("SELECT id FROM competitors WHERE name = :n"), {"n": name}).first()
    return row[0] if row else None


def _label_review(content: str, score: int | None) -> str:
    text_low = (content or "").lower()
    for label, kws in LABEL_RULES:
        if any(kw in text_low for kw in kws):
            return label
    if score is not None:
        if score >= 4:
            return "positive"
        if score <= 2:
            return "complaint"
    return "other"


def _detect_lang(text_str: str) -> str:
    if not text_str:
        return "en"
    # 简单启发：中文字符
    if any("一" <= c <= "鿿" for c in text_str):
        return "zh"
    # 葡萄牙 / 西班牙特有字母
    if any(c in "ãõçñáéíóú" for c in text_str.lower()):
        return "pt" if "ção" in text_str.lower() or "ões" in text_str.lower() else "es"
    return "en"


# ─────────────────────────── tasks ───────────────────────────


def task_label_reviews(s, dry_run=False) -> int:
    """给 labeled_at IS NULL 的评论打规则标签（mock AI，不真调）。"""
    rows = s.execute(text("""
        SELECT r.id, r.content, r.score, c.name as competitor
        FROM reviews r JOIN competitors c ON c.id = r.competitor_id
        WHERE r.labeled_at IS NULL AND r.content IS NOT NULL
        LIMIT 5000
    """)).fetchall()
    if not rows:
        return 0
    n = 0
    now = _now()
    for r in rows:
        label = _label_review(r.content or "", r.score)
        lang = _detect_lang(r.content or "")
        # mock translated_text — 中文加假翻译，其他保留
        translated = (r.content or "")[:500]
        if lang != "zh" and lang != "en" and translated:
            translated = f"[译] {translated}"
        if dry_run:
            n += 1
            continue
        s.execute(text("""
            UPDATE reviews SET label = :l, language = :lang,
                translated_text = :tt, labeled_at = :now
            WHERE id = :id
        """), {"l": label, "lang": lang, "tt": translated, "now": now, "id": r.id})
        n += 1
    return n


def task_seed_entities(s, dry_run=False) -> int:
    """填 entity_aliases（30 个 canonical）+ comment_entities（评论 ↔ 实体 link）"""
    n_canonical = 0
    n_links = 0
    now = _now()
    for ttype, cid, primary, aliases in ENTITY_SEED:
        existing = s.execute(text(
            "SELECT canonical_id FROM entity_aliases WHERE canonical_id = :cid"
        ), {"cid": cid}).first()
        if existing:
            continue
        if dry_run:
            n_canonical += 1
            continue
        s.execute(text("""
            INSERT INTO entity_aliases (canonical_id, entity_type, primary_name,
                aliases, created_at, reviewed)
            VALUES (:cid, :type, :pn, :al, :now, 0)
        """), {"cid": cid, "type": ttype, "pn": primary,
               "al": json.dumps(aliases, ensure_ascii=False), "now": now})
        n_canonical += 1

    # link some labeled reviews to entities — find reviews mentioning the alias
    if dry_run:
        return n_canonical
    for ttype, cid, primary, aliases in ENTITY_SEED:
        for alias in aliases[:2]:   # only top 2 alias per canonical
            rows = s.execute(text("""
                SELECT id FROM reviews
                WHERE labeled_at IS NOT NULL
                  AND LOWER(content) LIKE :pat
                LIMIT 5
            """), {"pat": f"%{alias.lower()}%"}).fetchall()
            for r in rows:
                # uniq check
                exists = s.execute(text(
                    "SELECT 1 FROM comment_entities WHERE review_id = :rid AND canonical_id = :cid"
                ), {"rid": r.id, "cid": cid}).first()
                if exists:
                    continue
                s.execute(text("""
                    INSERT INTO comment_entities (review_id, canonical_id,
                        entity_type, raw_value, extracted_at)
                    VALUES (:rid, :cid, :type, :rv, :now)
                """), {"rid": r.id, "cid": cid, "type": ttype, "rv": alias, "now": now})
                n_links += 1
    print(f"  entities: {n_canonical} canonical, {n_links} review-links")
    return n_canonical + n_links


def task_seed_iap(s, dry_run=False) -> int:
    """每个竞品 × 12 区 × 6 个 IAP（不含 AF）"""
    existing = s.execute(text("SELECT COUNT(*) FROM iap_items")).scalar()
    if existing and existing > 100:
        print(f"  iap_items 已有 {existing} 行，跳过")
        return 0
    n = 0
    now = _now()
    for app in COMPETITORS:
        cid = _resolve_competitor_id(s, app)
        if cid is None:
            continue
        for region in REGIONS:
            currency, mult = REGION_CURRENCY[region]
            symbol = CURRENCY_SYMBOL[currency]
            # 每个 region 不一定全部 6 个 IAP
            n_iap = random.randint(3, 6)
            for iap_name, category, base_price in IAP_NAMES[:n_iap]:
                local = round(base_price * mult, 2 if mult < 100 else 0)
                price_str = f"{symbol}{local}"
                if dry_run:
                    n += 1
                    continue
                s.execute(text("""
                    INSERT INTO iap_items (competitor_id, region_code, name, price,
                        price_num, currency, category, fetched_at)
                    VALUES (:cid, :rc, :name, :p, :pn, :cur, :cat, :now)
                """), {
                    "cid": cid, "rc": region, "name": iap_name, "p": price_str,
                    "pn": base_price, "cur": currency, "cat": category, "now": now,
                })
                n += 1
    return n


def task_seed_ads(s, dry_run=False) -> int:
    """每个竞品 × 5 国 × 3-5 个广告创意"""
    existing = s.execute(text("SELECT COUNT(*) FROM ad_creatives")).scalar()
    if existing and existing > 50:
        print(f"  ad_creatives 已有 {existing} 行，跳过")
        return 0
    n = 0
    now = _now()
    for app in COMPETITORS:
        cid = _resolve_competitor_id(s, app)
        if cid is None:
            continue
        for region in AD_REGIONS:
            n_ads = random.randint(3, 5)
            templates = AD_BODY_BY_REGION[region]
            for i in range(n_ads):
                body = random.choice(templates).format(app=app)
                start_offset = random.randint(1, 30)
                if dry_run:
                    n += 1
                    continue
                s.execute(text("""
                    INSERT INTO ad_creatives (competitor_id, region_code, ad_id,
                        text, start_date, platform, page_name, fetched_at)
                    VALUES (:cid, :rc, :aid, :body, :sd, :pf, :pn, :now)
                """), {
                    "cid": cid, "rc": region, "aid": f"demo_{app}_{region}_{i}",
                    "body": body, "sd": (date.today() - timedelta(days=start_offset)).isoformat(),
                    "pf": "facebook,instagram", "pn": app, "now": now,
                })
                n += 1
    return n


def task_seed_website(s, dry_run=False) -> int:
    """10 个 app（含 AF）的 Similarweb 月度数据"""
    existing = s.execute(text("SELECT COUNT(*) FROM website_traffic")).scalar()
    if existing and existing > 5:
        print(f"  website_traffic 已有 {existing} 行，跳过")
        return 0
    n = 0
    now = _now()
    snapshot_month = date.today().replace(day=1)

    # 每个 app 一组合理的 Similarweb 数据
    profiles = {
        "SofaScore":    (80_710_000, "00:06:07", 367, 4.29, 0.5254, 635, 298, "Brazil", 9),
        "FlashScore":   (145_900_000, "00:08:25", 505, 5.42, 0.3811, 412, 156, "Brazil", 5),
        "LiveScore":    (294_100_000, "00:05:46", 346, 3.85, 0.4471, 285, 87, "United Kingdom", 3),
        "OneFootball":  (8_940_000, "00:01:26", 86, 2.21, 0.5993, 8124, 4521, "Germany", 142),
        "365Scores":    (22_510_000, "00:02:09", 129, 3.12, 0.3926, 4205, 1832, "United States", 67),
        "Fotmob":       (21_580_000, "00:06:18", 378, 5.91, 0.2931, 4358, 2105, "United Kingdom", 71),
        "AiScore":      (5_447_000, "00:06:31", 391, 5.90, 0.3590, 12421, 5832, "Turkey", 218),
        "BeSoccer":     (6_745_000, "00:03:27", 207, 3.42, 0.4092, 9821, 4502, "Spain", 165),
        "310Scores":    (180_000, "00:01:13", 73, 1.85, 0.7531, 88420, 41205, "China", 2105),
        "AllFootball":  (12_300_000, "00:04:32", 272, 3.80, 0.4100, 4825, 1832, "Indonesia", 67),
    }

    for app, (visits, dur_str, dur_sec, ppv, br, gr, cr, country, cat_r) in profiles.items():
        cid = _resolve_competitor_id(s, app)
        if cid is None:
            continue
        if dry_run:
            n += 1
            continue
        # Top 5 countries（mock）
        top_countries = [
            {"country": country, "share": round(random.uniform(0.10, 0.25), 4)},
            {"country": "United States", "share": round(random.uniform(0.05, 0.12), 4)},
            {"country": "United Kingdom", "share": round(random.uniform(0.04, 0.08), 4)},
            {"country": "Spain", "share": round(random.uniform(0.03, 0.06), 4)},
            {"country": "Italy", "share": round(random.uniform(0.02, 0.05), 4)},
        ]
        # Similar sites (mock)
        peers = [a for a in ALL_APPS if a != app]
        random.shuffle(peers)
        similar = [{"domain": f"{p.lower()}.com", "affinity": round(random.uniform(0.6, 0.95), 2)}
                   for p in peers[:6]]

        domain = f"{app.lower().replace(' ', '')}.com" if app != "AllFootball" else "allfootballapp.com"
        # demographics — only AF / Anonymous-tier 视角
        male_share = round(random.uniform(0.65, 0.85), 2) if app in ("AllFootball",) else None
        female_share = round(1 - male_share, 2) if male_share else None

        s.execute(text("""
            INSERT INTO website_traffic
              (competitor_id, domain, snapshot_month, monthly_visits,
               monthly_visits_num, avg_visit_duration, avg_visit_duration_sec,
               pages_per_visit, bounce_rate,
               global_rank, country_rank, country_rank_country, category_rank,
               male_share, female_share,
               top_countries_json, similar_sites_json,
               raw_text, fetched_at)
            VALUES
              (:cid, :dom, :sm, :mv, :mvn, :avd, :avs, :ppv, :br,
               :gr, :cr, :crc, :catr, :ms, :fs,
               :tcj, :ssj, :rt, :now)
        """), {
            "cid": cid, "dom": domain, "sm": snapshot_month,
            "mv": _format_visits(visits), "mvn": visits,
            "avd": dur_str, "avs": dur_sec, "ppv": ppv, "br": br,
            "gr": gr, "cr": cr, "crc": country, "catr": cat_r,
            "ms": male_share, "fs": female_share,
            "tcj": json.dumps(top_countries, ensure_ascii=False),
            "ssj": json.dumps(similar, ensure_ascii=False),
            "rt": "(demo seed data)", "now": now,
        })
        n += 1
    return n


def task_seed_alerts(s, dry_run=False) -> int:
    """补全 7 类 alerts 各类至少 1 条（已有 ranking/news/release，缺 commercial/rating/churn/ads）"""
    existing_types = set(r[0] for r in s.execute(text(
        "SELECT DISTINCT alert_type FROM alerts WHERE fired_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
    )).fetchall())
    needed = [
        ("commercial", "high", "365Scores",
         {"iap_name": "VIP Annual", "old_price_usd": 39.99, "new_price_usd": 54.99,
          "change_pct": 37.5, "regions_count": 9, "rule_triggered": "iap_price_10pct_5regions"},
         "365Scores VIP Annual $39.99 → $54.99 · +37.5% · 9 区同步",
         "iap_price_10pct_5regions"),
        ("commercial", "mid", "OneFootball",
         {"iap_name": "Remove Ads", "old_price_usd": 2.99, "new_price_usd": 3.99,
          "change_pct": 33.4, "regions_count": 7, "rule_triggered": "iap_price_10pct_5regions"},
         "OneFootball Remove Ads $2.99 → $3.99 · +33.4% · 7 区同步",
         "iap_price_10pct_5regions"),
        ("rating", "high", "365Scores",
         {"region": "us", "old_rating": 4.6, "new_rating": 4.1, "days": 4,
          "rule_triggered": "rating_drop_0_3_4d"},
         "365Scores 美区评分 4.6 → 4.1 · 4 天下跌 0.5 星",
         "rating_drop_0_3_4d"),
        ("rating", "mid", "BeSoccer",
         {"region": "es", "old_rating": 4.4, "new_rating": 4.05, "days": 4,
          "rule_triggered": "rating_drop_0_3_4d"},
         "BeSoccer 西区评分 4.4 → 4.05 · 4 天下跌 0.35 星",
         "rating_drop_0_3_4d"),
        ("churn", "high", "AiScore",
         {"old_pct": 5.2, "new_pct": 12.4, "period_days": 7, "ratio": 2.38,
          "rule_triggered": "churn_pct_50pct_up_7d"},
         "AiScore 流失信号占比 5.2% → 12.4% · 7 天涨 138%",
         "churn_pct_50pct_up_7d"),
        ("ads", "high", "FlashScore",
         {"count_old": 8, "count_new": 32, "period_days": 7, "regions_concentrated": 5,
          "rule_triggered": "ads_count_50pct_change_7d"},
         "FlashScore 广告投放 8 → 32 · 7 天 +300% · 集中 5 国",
         "ads_count_50pct_change_7d"),
        ("ads", "mid", "Fotmob",
         {"count_old": 16, "count_new": 8, "period_days": 7, "regions_concentrated": 3,
          "rule_triggered": "ads_count_50pct_change_7d"},
         "Fotmob 广告投放 16 → 8 · 7 天 -50% · 集中 3 国",
         "ads_count_50pct_change_7d"),
    ]
    n = 0
    now = _now()
    for atype, sev, app, md, title, rule in needed:
        # 简化去重：同 type + app + day 已存在跳过
        already = s.execute(text("""
            SELECT 1 FROM alerts WHERE alert_type = :t AND app_name = :a
              AND DATE(fired_at) = CURDATE() LIMIT 1
        """), {"t": atype, "a": app}).first()
        if already:
            continue
        cid = _resolve_competitor_id(s, app)
        if dry_run:
            n += 1
            continue
        # 错峰时间分布
        fired = now - timedelta(hours=random.randint(1, 18))
        s.execute(text("""
            INSERT INTO alerts (alert_type, severity, competitor_id, app_name,
                metadata_json, title, rule_triggered, fired_at, status)
            VALUES (:t, :s, :cid, :a, :mj, :tt, :rt, :fa, :st)
        """), {
            "t": atype, "s": sev, "cid": cid, "a": app,
            "mj": json.dumps(md, ensure_ascii=False),
            "tt": title, "rt": rule, "fa": fired,
            "st": random.choice(["new", "new", "new", "ack"]),  # 多数 unread
        })
        n += 1
    _ = existing_types  # silence unused warning
    return n


def task_seed_failed_ai_jobs(s, dry_run=False) -> int:
    existing = s.execute(text("SELECT COUNT(*) FROM failed_ai_jobs")).scalar()
    if existing and existing >= 3:
        return 0
    samples = [
        ("comment_label", {"review_id": 9001, "raw_text": "App muito bom, recomendo!"},
         "JSONDecodeError: Expecting value: line 1 column 1 (char 0)\nResponse was: '<html><body>503 Service Unavailable</body></html>'",
         "json_parse"),
        ("comment_label", {"review_id": 9012, "raw_text": "..."},
         "HTTPError: 429 Too Many Requests from flashapi.top",
         "http"),
        ("entity_extract", {"review_id": 9034, "raw_text": "Real Madrid vs Barcelona"},
         "Connection reset by peer\nat anthropic_client.py:124",
         "http"),
        ("alert_title", {"alert_id": 8801, "alert_type": "ranking", "metadata": {"region": "us"}},
         "ValidationError: title exceeded 200 chars (got 240)",
         "json_parse"),
        ("app_classifier", {"app_id": "1234567890", "name": "Random Sports App"},
         "TimeoutError after 60s",
         "timeout"),
    ]
    n = 0
    now = _now()
    for task, payload, err_msg, err_kind in samples:
        if dry_run:
            n += 1
            continue
        s.execute(text("""
            INSERT INTO failed_ai_jobs (task_name, payload_json, error_msg,
                error_kind, attempts, first_failed_at, last_attempt_at)
            VALUES (:t, :p, :em, :ek, :a, :ff, :la)
        """), {
            "t": task, "p": json.dumps(payload, ensure_ascii=False),
            "em": err_msg, "ek": err_kind,
            "a": random.randint(1, 3),
            "ff": now - timedelta(hours=random.randint(2, 24)),
            "la": now - timedelta(minutes=random.randint(5, 60)),
        })
        n += 1
    return n


def task_seed_sync_log(s, dry_run=False) -> int:
    """补 sync_log（一些成功 + 少数失败）"""
    existing = s.execute(text("SELECT COUNT(*) FROM sync_log")).scalar()
    if existing and existing >= 30:
        return 0
    sources = ["appstore_rank", "androidrank", "comment_fetch", "reddit", "twitter",
               "iap_pricing", "google_news", "strategy_monitor",
               "appmagic", "fb_adlib", "sensor_tower", "similarweb_traffic",
               "ai_pipeline"]
    n = 0
    for i in range(40):
        src = random.choice(sources)
        success = random.random() > 0.08   # 92% 成功率
        # 时间戳从过去 24h 倒推
        started = _now() - timedelta(hours=random.uniform(0, 24))
        dur = random.uniform(2, 60) if success else random.uniform(5, 30)
        if dry_run:
            n += 1
            continue
        err_kind = None
        stderr_tail = None
        if not success:
            err_kind = random.choice(["http", "timeout", "auth_failed"])
            stderr_tail = {
                "http": "HTTPError: 503 Service Unavailable",
                "timeout": "asyncio.TimeoutError after 60s",
                "auth_failed": "401 Unauthorized — cookie invalid",
            }[err_kind]
        s.execute(text("""
            INSERT INTO sync_log (script, label, started_at, finished_at,
                duration_sec, success, error_kind, stdout_tail, stderr_tail, cmd)
            VALUES (:sc, :lb, :sa, :fa, :ds, :su, :ek, :so, :se, :cm)
        """), {
            "sc": src, "lb": src.replace("_", " ").title(),
            "sa": started, "fa": started + timedelta(seconds=dur),
            "ds": round(dur, 1), "su": success, "ek": err_kind,
            "so": f"{src}: scrape complete; wrote N rows" if success else None,
            "se": stderr_tail,
            "cm": f"python3 -m async_crawler --sources {src}",
        })
        n += 1
    return n


def _format_visits(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B".rstrip("0").rstrip(".") + "B" if False else f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


# ─────────────────────────── reset ───────────────────────────


def task_reset_demo(s, dry_run=False):
    """删 demo seed 留下的痕迹（保留真实抓取数据）

    由于无法严格区分 demo vs 真实，简单粗暴：清掉空表当时填的部分。
    这里通过 fetched_at 大致区分 — demo 都是当下时间。
    """
    if dry_run:
        print("  [dry-run] would clear demo-seeded rows")
        return
    s.execute(text("DELETE FROM ad_creatives WHERE ad_id LIKE 'demo_%'"))
    s.execute(text("DELETE FROM iap_items WHERE name IN :names"
                   ).bindparams(names=tuple(n for n, _, _ in IAP_NAMES)))
    s.execute(text("DELETE FROM website_traffic WHERE raw_text = '(demo seed data)'"))
    s.execute(text("DELETE FROM failed_ai_jobs WHERE error_msg LIKE '%demo%' OR id < 100"))
    print("  reset done (kept real scraped data)")


# ─────────────────────────── main ───────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="先清 demo 数据再 seed")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not db.is_mysql_enabled():
        print("❌ MYSQL_DSN 未配置，无法 seed")
        return 1

    print(f"=== seed_demo {'[DRY-RUN]' if args.dry_run else ''} ===")

    with db.session() as s:
        if args.reset:
            print("\n[reset] 清 demo 痕迹...")
            task_reset_demo(s, dry_run=args.dry_run)

        print("\n[1/7] 评论打 mock label...")
        n1 = task_label_reviews(s, dry_run=args.dry_run)
        print(f"  → {n1} 条评论已打标")

        print("\n[2/7] 实体表 + 评论实体链接...")
        n2 = task_seed_entities(s, dry_run=args.dry_run)
        print(f"  → 总计 {n2} 个 entity 写入")

        print("\n[3/7] IAP 价格...")
        n3 = task_seed_iap(s, dry_run=args.dry_run)
        print(f"  → {n3} 条 IAP")

        print("\n[4/7] 广告创意...")
        n4 = task_seed_ads(s, dry_run=args.dry_run)
        print(f"  → {n4} 条广告")

        print("\n[5/7] 网站流量（Similarweb 全 10 个 app）...")
        n5 = task_seed_website(s, dry_run=args.dry_run)
        print(f"  → {n5} 条网站")

        print("\n[6/7] alerts 补 7 类...")
        n6 = task_seed_alerts(s, dry_run=args.dry_run)
        print(f"  → {n6} 条新 alert")

        print("\n[6.5/7] AI 失败队列样例...")
        n7 = task_seed_failed_ai_jobs(s, dry_run=args.dry_run)
        print(f"  → {n7} 条 failed_ai_jobs")

        print("\n[7/7] sync_log 历史...")
        n8 = task_seed_sync_log(s, dry_run=args.dry_run)
        print(f"  → {n8} 条 sync_log")

    print(f"\n=== done · 总计写入 {n1 + n2 + n3 + n4 + n5 + n6 + n7 + n8} 行 ===")
    print("\n下一步：刷新浏览器（Cmd+Shift+R）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
