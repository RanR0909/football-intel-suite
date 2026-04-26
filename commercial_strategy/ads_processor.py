"""Facebook Ad Library 原始数据 → 业务指标。

输入：单个竞品的所有 fb_adlib standardize 后的 record 列表（按 region 分多条）。
输出：符合 AdsInfo schema 的 dict。

- Phase 1：规模 / 节奏 / 趋势 / 国家分布（不依赖关键词）
- Phase 2：themes / segments / patterns / top_creatives / creative_diversity（基于关键词字典）
Phase 3 由 ads_analyzer.py 独立完成，不在此处。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .ads_keywords import THEME_KEYWORDS, SEGMENT_KEYWORDS, PATTERN_KEYWORDS

NEW_ADS_WINDOW_DAYS = 3
TREND_HALF_WINDOW_DAYS = 7        # 最近 7d vs 之前 7d
TREND_THRESHOLD = 0.15            # ±15% 内算 stable，超出算 increasing/decreasing
TOP_THEMES_LIMIT = 5
TOP_SEGMENTS_LIMIT = 5
TOP_PATTERNS_LIMIT = 5
TOP_CREATIVES_LIMIT = 10
THEME_SAMPLE_LIMIT = 3            # 每个 theme 附带的代表性原文条数
SEGMENT_HIGH_THRESHOLD = 5
SEGMENT_MEDIUM_THRESHOLD = 2
TEXT_HASH_PREFIX = 100            # 唯一度判断时取文案前 N 字


def _parse_date(value) -> datetime | None:
    """fb_adlib 抓的 start_date 可能是 ISO 串、unix timestamp 或空。"""
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    s = str(value).strip()
    if not s:
        return None
    # 尝试几种常见格式
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # 数字串当 unix timestamp
    try:
        return datetime.fromtimestamp(float(s), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _hit_keywords(text: str, dictionary: dict) -> list[str]:
    """返回 text 命中的所有 label（命中字典中任意一个关键词即归该 label）。"""
    if not text:
        return []
    low = text.lower()
    hits = []
    for label, keywords in dictionary.items():
        if any(kw in low for kw in keywords):
            hits.append(label)
    return hits


def _signal_strength(count: int) -> str:
    if count >= SEGMENT_HIGH_THRESHOLD:
        return "high"
    if count >= SEGMENT_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _classify_trend(recent: int, prior: int) -> tuple[str, float]:
    if prior == 0:
        if recent == 0:
            return "stable", 0.0
        return "increasing", 1.0
    pct = (recent - prior) / prior
    if pct > TREND_THRESHOLD:
        return "increasing", pct
    if pct < -TREND_THRESHOLD:
        return "decreasing", pct
    return "stable", pct


def process_competitor_ads(records: list[dict]) -> dict:
    """records 是单个竞品的所有 fb_adlib 记录（多 region）。

    fb_adlib 抓取的均为 active_status=active，故 active_count 即去重后总数。
    一次扫描完成 Phase 1 统计 + Phase 2 关键词命中 + 代表性素材抽取。
    """
    if not records:
        return {}

    now = datetime.now(timezone.utc)
    cutoff_new = now - timedelta(days=NEW_ADS_WINDOW_DAYS)
    cutoff_recent = now - timedelta(days=TREND_HALF_WINDOW_DAYS)
    cutoff_prior = now - timedelta(days=TREND_HALF_WINDOW_DAYS * 2)

    # --- Phase 1 累加器 ---
    seen: set[str] = set()
    by_country: Counter = Counter()
    daily: dict[str, int] = defaultdict(int)
    new_ads = 0
    recent_bucket = 0
    prior_bucket = 0
    last_ts: str = ""

    # --- Phase 2 累加器 ---
    theme_count: Counter = Counter()
    theme_samples: dict[str, list] = defaultdict(list)
    segment_count: Counter = Counter()
    pattern_count: Counter = Counter()
    bodies_total = 0
    body_prefixes: set = set()                # 去重判断"唯一文案数"
    creatives: list[dict] = []                # 用于 top_creatives

    for rec in records:
        ts = rec.get("timestamp") or ""
        if ts > last_ts:
            last_ts = ts
        rec_country = (rec.get("region") or "").upper()

        for ad in (rec.get("data", {}) or {}).get("ads") or []:
            ad_id = ad.get("ad_id")
            if not ad_id or ad_id in seen:
                continue
            seen.add(ad_id)
            country = (ad.get("country") or rec_country or "??").upper()
            by_country[country] += 1

            start = _parse_date(ad.get("start_date"))
            if start:
                daily[start.strftime("%Y-%m-%d")] += 1
                if start >= cutoff_new:
                    new_ads += 1
                if start >= cutoff_recent:
                    recent_bucket += 1
                elif start >= cutoff_prior:
                    prior_bucket += 1

            # fb_adlib 实际产物字段是 "text"（不是 "bodyText"），保留 bodyText 兼容性
            body = (ad.get("text") or ad.get("bodyText") or "").strip()
            ad_themes: list[str] = []
            if body:
                bodies_total += 1
                body_prefixes.add(body[:TEXT_HASH_PREFIX])
                ad_themes = _hit_keywords(body, THEME_KEYWORDS)
                segments = _hit_keywords(body, SEGMENT_KEYWORDS)
                patterns = _hit_keywords(body, PATTERN_KEYWORDS)
                for t in ad_themes:
                    theme_count[t] += 1
                    if len(theme_samples[t]) < THEME_SAMPLE_LIMIT:
                        theme_samples[t].append(body[:120])
                for s in segments:
                    segment_count[s] += 1
                for p in patterns:
                    pattern_count[p] += 1

            days_running = max(0, (now - start).days) if start else 0
            creatives.append({
                "ad_id": ad_id,
                "body_text": body[:500],
                "media_url": ad.get("media_url") or None,
                "country": country,
                "days_running": days_running,
                "start_date": start.strftime("%Y-%m-%d") if start else None,
                "themes": ad_themes,
            })

    trend, trend_pct = _classify_trend(recent_bucket, prior_bucket)

    top_themes = [
        {"theme": theme, "count": cnt, "samples": theme_samples.get(theme, [])}
        for theme, cnt in theme_count.most_common(TOP_THEMES_LIMIT)
    ]
    user_segments = [
        {"segment": seg, "count": cnt, "signal_strength": _signal_strength(cnt)}
        for seg, cnt in segment_count.most_common(TOP_SEGMENTS_LIMIT)
    ]
    creative_patterns = [
        {"pattern": pat, "count": cnt}
        for pat, cnt in pattern_count.most_common(TOP_PATTERNS_LIMIT)
    ]
    diversity = round(len(body_prefixes) / bodies_total, 2) if bodies_total else 0.0
    top_creatives = sorted(creatives, key=lambda x: x["days_running"], reverse=True)[:TOP_CREATIVES_LIMIT]

    return {
        # Phase 1
        "active_count": len(seen),
        "new_ads": new_ads,
        "trend": trend,
        "trend_pct": round(trend_pct, 2),
        "by_country": dict(by_country),
        "daily_trend": [{"date": d, "new": v} for d, v in sorted(daily.items())],
        "last_updated": last_ts or None,
        # Phase 2
        "top_themes": top_themes,
        "user_segments": user_segments,
        "creative_patterns": creative_patterns,
        "creative_diversity": diversity,
        "top_creatives": top_creatives,
    }
