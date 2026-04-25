"""
market_rank.py - App Store Sports Category Leaderboard Tracker

Fetches the Top 100 free apps from the App Store "Sports" category (ID: 6004),
tracks ranking history, computes day-over-day rank changes (delta),
highlights known competitor apps, detects new contenders and fast movers,
and generates AI-powered market briefings.

Data sources:
  - Apple iTunes RSS feed: https://itunes.apple.com/us/rss/topfreeapplications/limit=100/genre=6004/json
  - COMPETITORS dict (the same 6 core competitors used across the suite)
  - data/competitors.json (shared competitor registry)
  - data/ranking_history.json (persistent history)
  - OpenAI-compatible API (opus-4-6) for AI market analysis
"""

import json
import os
import re
import ssl
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import urllib.request
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import streamlit as st
import sys


class SSLAdapter(HTTPAdapter):
    """Adapter that forces TLS 1.2 to avoid SSL EOF errors on macOS."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

# ---------------------------------------------------------------------------
# 路径自动定位 — 统一指向 Football_Intel_Suite/data/
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent          # Football_Intel_Suite/
DATA_DIR = _PROJECT_ROOT / "data"           # 统一数据输出目录
sys.path.insert(0, str(_PROJECT_ROOT))

from competitors import get_market_rank_competitors

RANKING_HISTORY_PATH = DATA_DIR / "ranking_history.json"

APP_STORE_URL = (
    "https://itunes.apple.com/us/rss/topfreeapplications"
    "/limit=100/genre=6004/json"
)

# Claude API configuration
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

# Thresholds for market alerts
NEW_CONTENDER_TOP_N = 50  # Apps in top N not in known list
FAST_MOVER_THRESHOLD = 15  # Rank improvement of at least this many positions
NEW_CONTENDER_RISE_THRESHOLD = 10  # 过去7天内排名上升至少10位才视为新晋竞争者
NEW_CONTENDER_LOOKBACK_DAYS = 7  # 回溯天数

COMPETITORS: dict[str, dict[str, str | int]] = get_market_rank_competitors()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict:
    """Load a JSON file, returning an empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, dict) else {}


def save_json(path: Path, data: dict | list) -> None:
    """Persist data to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_session() -> requests.Session:
    """Create a requests Session with SSL adapter for macOS compatibility."""
    session = requests.Session()
    adapter = SSLAdapter()
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "MarketRank/1.0"})
    return session


def fetch_top_free_sports() -> list[dict]:
    """
    Fetch the Top 100 free apps from the App Store Sports category.

    Returns a list of dicts with keys:
        rank, app_id, name, bundle_id, artist, icon_url, app_url
    """
    session = _get_session()
    resp = session.get(APP_STORE_URL, timeout=30)
    resp.raise_for_status()
    feed = resp.json().get("feed", {})
    entries = feed.get("entry", [])

    results: list[dict] = []
    for idx, entry in enumerate(entries, start=1):
        name = entry.get("im:name", {}).get("label", "Unknown")
        app_id = entry.get("id", {}).get("attributes", {}).get("im:id", "")
        bundle_id = entry.get("id", {}).get("attributes", {}).get("im:bundleId", "")
        artist = entry.get("im:artist", {}).get("label", "")
        icon_url = ""
        images = entry.get("im:image", [])
        if images:
            # Pick the largest icon (100x100)
            icon_url = images[-1].get("label", "")
        app_url = entry.get("id", {}).get("label", "")

        results.append(
            {
                "rank": idx,
                "app_id": app_id,
                "name": name,
                "bundle_id": bundle_id,
                "artist": artist,
                "icon_url": icon_url,
                "app_url": app_url,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Multi-Source Data Collection
# ---------------------------------------------------------------------------

MARKET_HISTORY_PATH = DATA_DIR / "market_history.csv"

# Androidrank uses custom URL slugs, not derivable from package names
ANDROIDRANK_SLUGS = {
    "com.sofascore.results": "sofascore_sports_live_score/com.sofascore.results",
    "eu.livesport.FlashScore_com": "flashscore_live_scores_news/eu.livesport.FlashScore_com",
    "de.motain.iliga": "onefootball_all_soccer_scores/de.motain.iliga",
    "com.scores365": "365scores_live_scores_news/com.scores365",
    "com.mobilefootie.fotmobpro": "fotmob_pro_live_soccer_scores/com.mobilefootie.fotmobpro",
    "com.livescore": "livescore_live_sports_scores/com.livescore",
}

# Some GP package names differ from what's in competitors.json — override here
GP_PACKAGE_OVERRIDES = {
    "FlashScore": "eu.livesport.FlashScore_com",
    "OneFootball": "de.motain.iliga",
    "365Scores": "com.scores365",
    "Fotmob": "com.mobilefootie.fotmobpro",
    "LiveScore": "com.livescore",
}


def _parse_js_array(raw: str) -> list:
    import re as _re
    cleaned = _re.sub(r',\s*\]', ']', raw)
    return json.loads(cleaned)


def fetch_androidrank_data(package_name: str) -> dict:
    """Fetch download range, rating count, category rank from Androidrank."""
    import re as _re
    slug = ANDROIDRANK_SLUGS.get(package_name)
    if slug:
        url = f"https://www.androidrank.org/application/{slug}"
    else:
        url = f"https://www.androidrank.org/application/{package_name.replace('.', '_')}/{package_name}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MarketRank/1.0"})
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e)}

    result = {}

    m = _re.search(r'drawChartDownloadsEstimationData = (\[.*?\]);', html)
    if m:
        try:
            history = _parse_js_array(m.group(1))
            result["download_history"] = history
            if history:
                result["estimated_downloads"] = history[-1][1]
        except Exception:
            pass

    m = _re.search(r'drawChartRankAvgData = (\[.*?\]);', html)
    if m:
        try:
            history = _parse_js_array(m.group(1))
            result["rating_history"] = history
            if history:
                result["current_rating"] = history[-1][1]
        except Exception:
            pass

    m = _re.search(r'drawChartRankTotalData = (\[.*?\]);', html)
    if m:
        try:
            history = _parse_js_array(m.group(1))
            result["total_ratings_history"] = history
            if history:
                result["total_ratings"] = history[-1][1]
        except Exception:
            pass

    return result


def fetch_sensor_tower_data(package_name: str) -> dict:
    """Fetch download trend, revenue range, category rank from Sensor Tower public API."""
    url = f"https://app.sensortower.com/api/android/apps/{package_name}?country=US"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

    result = {}

    rev = data.get("worldwide_last_month_revenue")
    if rev and isinstance(rev, dict):
        val = rev.get("value", 0)
        unit = rev.get("unit", "")
        result["monthly_revenue_cents"] = val
        result["monthly_revenue_usd"] = val / 100 if unit == "cent" else val

    dl = data.get("worldwide_last_month_downloads")
    if dl and isinstance(dl, dict):
        result["monthly_downloads"] = dl.get("value", 0)

    result["rating"] = data.get("rating")
    result["rating_count"] = data.get("rating_count")
    result["installs_text"] = data.get("installs", "")
    result["top_countries"] = data.get("top_countries", [])

    cr = data.get("category_rankings", {}).get("android", {})
    if isinstance(cr, dict):
        tf = cr.get("top_free", {})
        tg = cr.get("top_grossing", {})
        if tf and tf.get("primary_categories"):
            for cat in tf["primary_categories"]:
                if isinstance(cat, dict):
                    result["category_rank_free"] = list(cat.values())[0]
                    break
        if tg and tg.get("primary_categories"):
            for cat in tg["primary_categories"]:
                if isinstance(cat, dict):
                    result["category_rank_grossing"] = list(cat.values())[0]
                    break

    result["current_version"] = data.get("current_version", "")
    result["publisher_country"] = data.get("publisher_country", "")

    rb = data.get("rating_breakdown")
    if isinstance(rb, list) and len(rb) == 5:
        result["rating_breakdown"] = {
            "1star": rb[0], "2star": rb[1], "3star": rb[2],
            "4star": rb[3], "5star": rb[4],
        }

    return result


def fetch_store_data(package_name: str, app_id: str) -> dict:
    """Fetch ranking, reviews, rating, version from Google Play + App Store."""
    result = {}

    try:
        from google_play_scraper import app as gp_app, reviews as gp_reviews, Sort
        info = gp_app(package_name)
        result["gp"] = {
            "installs": info.get("realInstalls"),
            "score": info.get("score"),
            "ratings": info.get("ratings"),
            "reviews_count": info.get("reviews"),
            "version": info.get("version", ""),
            "updated": info.get("updated"),
            "developer": info.get("developer", ""),
            "iap": info.get("offersIAP"),
        }
        try:
            recent, _ = gp_reviews(package_name, lang="en", country="us",
                                   sort=Sort.NEWEST, count=5)
            result["gp"]["recent_reviews"] = [
                {"score": r["score"], "text": (r.get("content") or "")[:200]}
                for r in recent[:5]
            ]
        except Exception:
            pass
    except Exception as e:
        result["gp"] = {"error": str(e)}

    try:
        lookup_url = f"https://itunes.apple.com/lookup?id={app_id}"
        req = urllib.request.Request(lookup_url, headers={"User-Agent": "MarketRank/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("resultCount", 0) > 0:
            ai = data["results"][0]
            result["ios"] = {
                "version": ai.get("version", ""),
                "score": ai.get("averageUserRating"),
                "ratings": ai.get("userRatingCount"),
                "current_version_score": ai.get("averageUserRatingForCurrentVersion"),
                "release_date": ai.get("currentVersionReleaseDate", ""),
                "release_notes": (ai.get("releaseNotes") or "")[:500],
            }
        else:
            result["ios"] = {"error": "not found"}
    except Exception as e:
        result["ios"] = {"error": str(e)}

    return result


def fetch_reddit_mentions(app_name: str) -> dict:
    """Search Reddit for app mentions, return count and sentiment proxy."""
    import re as _re
    query = f"{app_name} app"
    url = f"https://www.reddit.com/search.json?q={urllib.parse.quote(query)}&sort=new&limit=25&t=month"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "MarketRank/1.0 (competitive-intel)",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

    posts = data.get("data", {}).get("children", [])
    if not posts:
        return {"mention_count": 0, "sentiment_score": 0.0, "posts": []}

    scores = []
    post_summaries = []
    for p in posts:
        pd = p.get("data", {})
        upvote_ratio = pd.get("upvote_ratio", 0.5)
        score = pd.get("score", 0)
        scores.append(upvote_ratio)
        post_summaries.append({
            "title": (pd.get("title") or "")[:120],
            "subreddit": pd.get("subreddit", ""),
            "score": score,
            "upvote_ratio": upvote_ratio,
            "created": pd.get("created_utc"),
        })

    sentiment = sum(scores) / len(scores) if scores else 0.5
    sentiment_normalized = round((sentiment - 0.5) * 2, 3)

    return {
        "mention_count": len(posts),
        "sentiment_score": sentiment_normalized,
        "posts": post_summaries[:10],
    }


def _compute_rating_growth(androidrank_data: dict) -> Optional[float]:
    """Compute rating count growth rate from Androidrank history."""
    history = androidrank_data.get("total_ratings_history", [])
    if len(history) < 2:
        return None
    prev = history[-2][1]
    curr = history[-1][1]
    if prev <= 0:
        return None
    return round((curr - prev) / prev, 4)


def _compute_update_frequency(store_data: dict) -> Optional[float]:
    """Estimate update frequency (days between updates) from store data."""
    ios = store_data.get("ios", {})
    release_date = ios.get("release_date", "")
    if not release_date:
        return None
    try:
        from datetime import datetime as _dt
        rd = _dt.fromisoformat(release_date.replace("Z", "+00:00"))
        days_since = (datetime.now(rd.tzinfo or None) - rd).days
        return max(days_since, 0)
    except Exception:
        return None


def aggregate_market_data(competitors: dict) -> list[dict]:
    """
    Fetch all sources for each competitor and produce unified records:
    {app, rank, download_proxy, rating_growth, revenue_proxy,
     sentiment_score, update_frequency, timestamp}
    """
    from competitors import load_competitors
    full_comps = load_competitors()
    records = []
    ts = datetime.now().isoformat()

    for comp_name, comp_info in competitors.items():
        app_id = str(comp_info.get("app_id", ""))
        full = full_comps.get(comp_name, {})
        gp_package = full.get("gp", "") or comp_info.get("bundle_id", "")
        ar_package = GP_PACKAGE_OVERRIDES.get(comp_name) or gp_package

        print(f"\n  [{comp_name}]")
        rec = {"app": comp_name, "timestamp": ts}

        # 1. Androidrank
        if ar_package:
            print(f"    Androidrank...", end=" ", flush=True)
            ar = fetch_androidrank_data(ar_package)
            if "error" not in ar:
                rec["download_proxy"] = ar.get("estimated_downloads")
                rec["rating_growth"] = _compute_rating_growth(ar)
                print(f"OK (downloads={ar.get('estimated_downloads')})")
            else:
                print(f"FAIL ({ar['error'][:60]})")
        else:
            ar = {}

        # 2. Sensor Tower
        if ar_package:
            print(f"    Sensor Tower...", end=" ", flush=True)
            st_data = fetch_sensor_tower_data(ar_package)
            if "error" not in st_data:
                rec["revenue_proxy"] = st_data.get("monthly_revenue_usd")
                rec["rank"] = st_data.get("category_rank_free")
                if not rec.get("download_proxy"):
                    rec["download_proxy"] = st_data.get("monthly_downloads")
                print(f"OK (rev=${st_data.get('monthly_revenue_usd', 0):.0f}, rank={st_data.get('category_rank_free')})")
            else:
                print(f"FAIL ({st_data['error'][:60]})")
        else:
            st_data = {}

        # 3. Store data (GP + iOS)
        if gp_package and app_id:
            print(f"    Store...", end=" ", flush=True)
            sd = fetch_store_data(gp_package, app_id)
            gp_ok = "error" not in sd.get("gp", {})
            ios_ok = "error" not in sd.get("ios", {})
            rec["update_frequency"] = _compute_update_frequency(sd)
            if not rec.get("download_proxy") and gp_ok:
                rec["download_proxy"] = sd["gp"].get("installs")
            print(f"GP={'OK' if gp_ok else 'FAIL'} iOS={'OK' if ios_ok else 'FAIL'}")
        else:
            sd = {}

        # 4. Reddit mentions
        print(f"    Reddit...", end=" ", flush=True)
        reddit = fetch_reddit_mentions(comp_name)
        if "error" not in reddit:
            rec["sentiment_score"] = reddit.get("sentiment_score", 0.0)
            print(f"OK ({reddit.get('mention_count', 0)} mentions)")
        else:
            rec["sentiment_score"] = 0.0
            print(f"FAIL ({reddit.get('error', '')[:60]})")

        # Fill defaults
        rec.setdefault("rank", None)
        rec.setdefault("download_proxy", None)
        rec.setdefault("rating_growth", None)
        rec.setdefault("revenue_proxy", None)
        rec.setdefault("sentiment_score", 0.0)
        rec.setdefault("update_frequency", None)

        rec["_raw"] = {
            "androidrank": ar,
            "sensor_tower": st_data,
            "store": sd,
            "reddit": reddit,
        }

        records.append(rec)

    return records


def save_market_csv(records: list[dict]) -> Path:
    """Append unified records to market_history.csv."""
    import csv
    fields = ["app", "rank", "download_proxy", "rating_growth",
              "revenue_proxy", "sentiment_score", "update_frequency", "timestamp"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = MARKET_HISTORY_PATH.exists()
    with open(MARKET_HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k) for k in fields})
    print(f"CSV 已追加: {MARKET_HISTORY_PATH} ({len(records)} 条)")
    return MARKET_HISTORY_PATH


def build_known_apps() -> dict[str, dict[str, str | int]]:
    """Load all configured competitors from the shared registry."""
    return get_market_rank_competitors()


def load_ranking_history() -> dict:
    """Load the ranking history file."""
    return load_json(RANKING_HISTORY_PATH)


def save_ranking_history(history: dict) -> None:
    """Save the ranking history file."""
    save_json(RANKING_HISTORY_PATH, history)


def get_today_key() -> str:
    """Return today's date as a string key (YYYY-MM-DD)."""
    return date.today().isoformat()


def get_yesterday_key() -> str:
    """Return yesterday's date as a string key (YYYY-MM-DD)."""
    return (date.today() - timedelta(days=1)).isoformat()


def compute_delta(
    history: dict,
    today_key: str,
    yesterday_key: str,
    app_id: str,
    current_rank: int,
) -> Optional[int]:
    """
    Compute the rank change (delta) for an app between today and yesterday.

    Positive delta = rank improved (moved up).
    Negative delta = rank declined (moved down).
    None = no previous data.
    """
    today_data = history.get(today_key, {})
    yesterday_data = history.get(yesterday_key, {})

    yesterday_rank = yesterday_data.get(app_id)
    if yesterday_rank is None:
        return None

    return yesterday_rank - current_rank


def is_known_app(known_apps: dict, app_id: str, name: str) -> bool:
    """Check if an app is in our known competitors list."""
    for info in known_apps.values():
        if str(info.get("app_id", "")) == app_id:
            return True
        if info.get("name", "") == name:
            return True
    return False


def get_competitor_rank(
    today_ranking: list[dict], app_id: str
) -> Optional[int]:
    """Find the current rank of a competitor by app_id."""
    for app in today_ranking:
        if app["app_id"] == app_id:
            return app["rank"]
    return None


# ---------------------------------------------------------------------------
# Market Alert Detection
# ---------------------------------------------------------------------------


def detect_new_contenders(
    today_ranking: list[dict],
    history: dict,
    today_key: str,
    top_n: int = NEW_CONTENDER_TOP_N,
    rise_threshold: int = NEW_CONTENDER_RISE_THRESHOLD,
    lookback_days: int = NEW_CONTENDER_LOOKBACK_DAYS,
) -> list[dict]:
    """
    Identify apps in the top N whose rank has risen by at least `rise_threshold`
    positions over the past `lookback_days` days.

    Compares today's rank with the rank from `lookback_days` ago.
    If no data exists from that far back, falls back to the earliest available
    date within the lookback window.

    Returns a list of app dicts (with delta added) sorted by delta descending.
    """
    # Collect all date keys within the lookback window
    today = date.fromisoformat(today_key)
    candidate_dates = []
    for i in range(1, lookback_days + 1):
        d = (today - timedelta(days=i)).isoformat()
        if d in history:
            candidate_dates.append(d)

    if not candidate_dates:
        return []

    contenders = []
    for app in today_ranking:
        if app["rank"] > top_n:
            break

        app_id = app["app_id"]
        current_rank = app["rank"]

        # Find the earliest available rank within the lookback window
        past_rank = None
        for d in candidate_dates:
            past_rank = history[d].get(app_id)
            if past_rank is not None:
                break

        if past_rank is None:
            continue

        delta = past_rank - current_rank
        if delta >= rise_threshold:
            app_with_delta = dict(app)
            app_with_delta["delta"] = delta
            contenders.append(app_with_delta)

    # Sort by delta descending (biggest mover first)
    contenders.sort(key=lambda x: x["delta"], reverse=True)
    return contenders


def detect_fast_movers(
    today_ranking: list[dict],
    history: dict,
    today_key: str,
    yesterday_key: str,
    threshold: int = FAST_MOVER_THRESHOLD,
) -> list[dict]:
    """
    Identify apps whose rank improved by at least `threshold` positions
    in the last 24 hours.

    Returns a list of app dicts (with delta added) sorted by delta descending.
    """
    yesterday_data = history.get(yesterday_key, {})
    if not yesterday_data:
        return []

    fast_movers = []
    for app in today_ranking:
        app_id = app["app_id"]
        yesterday_rank = yesterday_data.get(app_id)
        if yesterday_rank is None:
            continue
        delta = yesterday_rank - app["rank"]
        if delta >= threshold:
            app_with_delta = dict(app)
            app_with_delta["delta"] = delta
            fast_movers.append(app_with_delta)

    # Sort by delta descending (biggest mover first)
    fast_movers.sort(key=lambda x: x["delta"], reverse=True)
    return fast_movers


# ---------------------------------------------------------------------------
# AI Market Briefing
# ---------------------------------------------------------------------------


def generate_ai_market_brief(
    new_contenders: list[dict],
    fast_movers: list[dict],
) -> Optional[str]:
    if not CLAUDE_API_KEY or (not new_contenders and not fast_movers):
        return None

    contenders_text = "\n".join(
        f"  - {a['name']} (by {a['artist']}, rank #{a['rank']})"
        for a in new_contenders
    ) if new_contenders else "  (none)"

    movers_text = "\n".join(
        f"  - {a['name']} (by {a['artist']}, "
        f"moved up {a['delta']} spots to #{a['rank']})"
        for a in fast_movers
    ) if fast_movers else "  (none)"

    prompt = (
        "You are a senior product growth expert with deep experience in "
        "mobile app market analysis, competitive intelligence, and user "
        "acquisition strategy. Analyze the following App Store Sports "
        "category leaderboard data and provide a concise market briefing.\n\n"
        "Today's date: " + date.today().isoformat() + "\n\n"
        "=== New Contenders (apps in Top 50 not previously tracked) ===\n"
        + contenders_text + "\n\n"
        "=== Fast Movers (apps that gained 15+ ranks in 24 hours) ===\n"
        + movers_text + "\n\n"
        "Please analyze:\n"
        "1. For each notable app, predict the most likely reason for its "
        "rank surge (e.g., major sports event driving downloads, aggressive "
        "user acquisition campaign, viral new feature launch, seasonal effect).\n"
        "2. Assess the threat level of each potential competitor on a scale "
        "of Low / Medium / High, with a brief justification.\n"
        "3. Provide a one-sentence strategic recommendation for our team.\n\n"
        "Keep the total response under 300 words. Be specific and data-driven."
    )

    data = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://ai.flashapi.top/v1/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
        }
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            result = json.loads(resp.read())
        return result["content"][0]["text"].strip()
    except Exception as e:
        st.warning(f"AI market briefing unavailable: {e}")
        return None


# ---------------------------------------------------------------------------
# JSON Export — for main dashboard
# ---------------------------------------------------------------------------


def export_json(today_ranking: list[dict], history: dict, known_apps: dict,
                new_contenders: list[dict], fast_movers: list[dict],
                ai_brief: Optional[str],
                multi_source_data: Optional[dict] = None) -> None:
    """Export structured JSON to root /data/ for the main dashboard."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "market_rank.json"

    today_key = get_today_key()
    yesterday_key = get_yesterday_key()

    # Build competitor performance data
    competitor_performance = {}
    for comp_name, comp_info in COMPETITORS.items():
        app_id = str(comp_info["app_id"])
        rank = get_competitor_rank(today_ranking, app_id)
        if rank is not None:
            delta_val = compute_delta(history, today_key, yesterday_key, app_id, rank)
            competitor_performance[comp_name] = {
                "rank": rank,
                "delta": delta_val,
                "app_id": app_id,
            }
        else:
            competitor_performance[comp_name] = {
                "rank": None,
                "delta": None,
                "app_id": app_id,
            }

    # Build full leaderboard with deltas
    leaderboard = []
    for app in today_ranking:
        app_id = app["app_id"]
        delta_val = compute_delta(history, today_key, yesterday_key, app_id, app["rank"])
        leaderboard.append({
            "rank": app["rank"],
            "name": app["name"],
            "app_id": app_id,
            "artist": app["artist"],
            "delta": delta_val,
            "is_known": is_known_app(known_apps, app_id, app["name"]),
        })

    data = {
        "generated_at": datetime.now().isoformat(),
        "date": today_key,
        "total_apps": len(today_ranking),
        "competitor_performance": competitor_performance,
        "new_contenders": [
            {"rank": a["rank"], "name": a["name"], "artist": a["artist"], "delta": a.get("delta")}
            for a in new_contenders
        ],
        "fast_movers": [
            {"rank": a["rank"], "name": a["name"], "delta": a["delta"], "artist": a["artist"]}
            for a in fast_movers
        ],
        "ai_brief": ai_brief,
        "leaderboard": leaderboard,
    }

    if multi_source_data:
        data["multi_source"] = multi_source_data

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据已导出: {out_path}")


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="App Store Sports Leaderboard",
    page_icon=None,  # No emoji per constraint
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -- Light theme via custom CSS --
st.markdown(
    """
    <style>
    .main {
        background-color: #ffffff;
    }
    .stApp {
        background-color: #ffffff;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #1a1a2e;
    }
    .competitor-metric {
        background-color: #f0f2f6;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    .market-alert {
        background-color: #fff3e0;
        border-left: 4px solid #e65100;
        padding: 16px;
        border-radius: 4px;
        margin-bottom: 16px;
    }
    .market-alert h3 {
        color: #e65100;
        margin-top: 0;
    }
    .market-alert .contender-item {
        padding: 4px 0;
        font-size: 14px;
    }
    .market-alert .contender-rank {
        font-weight: 600;
        color: #bf360c;
    }
    .ai-brief {
        background-color: #e8f5e9;
        border-left: 4px solid #2e7d32;
        padding: 16px;
        border-radius: 4px;
        margin-bottom: 16px;
        white-space: pre-wrap;
        font-size: 14px;
        line-height: 1.6;
    }
    .ai-brief h3 {
        color: #2e7d32;
        margin-top: 0;
    }
    .fast-mover-item {
        padding: 4px 0;
        font-size: 14px;
    }
    .fast-mover-delta {
        font-weight: 600;
        color: #1565c0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("App Store Sports Category - Top 100 Free Apps")
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

known_apps = build_known_apps()
history = load_ranking_history()
today_key = get_today_key()
yesterday_key = get_yesterday_key()

# Fetch today's ranking
with st.spinner("Fetching App Store leaderboard..."):
    try:
        today_ranking = fetch_top_free_sports()
    except Exception as e:
        st.error(f"Failed to fetch App Store data: {e}")
        st.stop()

# Store today's ranking in history
today_data: dict[str, int] = {}
for app in today_ranking:
    today_data[app["app_id"]] = app["rank"]

history[today_key] = today_data
save_ranking_history(history)

# ---------------------------------------------------------------------------
# Section 0: Market Alerts (New Contenders + Fast Movers)
# ---------------------------------------------------------------------------

new_contenders = detect_new_contenders(today_ranking, history, today_key)
fast_movers = detect_fast_movers(
    today_ranking, history, today_key, yesterday_key
)

if new_contenders or fast_movers:
    st.markdown("## Market Alert")

    if new_contenders:
        contender_html = '<div class="market-alert">'
        contender_html += "<h3>New Contenders Detected</h3>"
        contender_html += (
            "<p style='margin-bottom:8px;'>"
            "The following apps have entered the Top "
            f"{NEW_CONTENDER_TOP_N} and are not in your known competitor list:"
            "</p>"
        )
        for app in new_contenders[:10]:  # Show top 10
            contender_html += (
                '<div class="contender-item">'
                f'<span class="contender-rank">#{app["rank"]}</span> '
                f'{app["name"]}'
                f'<span style="color:#666;font-size:12px;"> by {app["artist"]}</span>'
                "</div>"
            )
        if len(new_contenders) > 10:
            contender_html += (
                f'<div style="color:#666;font-size:12px;margin-top:4px;">'
                f'... and {len(new_contenders) - 10} more</div>'
            )
        contender_html += "</div>"
        st.markdown(contender_html, unsafe_allow_html=True)

    if fast_movers:
        mover_html = '<div class="market-alert">'
        mover_html += "<h3>Fast Movers Detected</h3>"
        mover_html += (
            "<p style='margin-bottom:8px;'>"
            "The following apps gained "
            f"{FAST_MOVER_THRESHOLD}+ positions in the last 24 hours:"
            "</p>"
        )
        for app in fast_movers[:10]:
            mover_html += (
                '<div class="fast-mover-item">'
                f'<span class="fast-mover-delta">+{app["delta"]}</span> '
                f'{app["name"]} '
                f'<span style="color:#666;font-size:12px;">'
                f'(now #{app["rank"]})</span>'
                "</div>"
            )
        if len(fast_movers) > 10:
            mover_html += (
                f'<div style="color:#666;font-size:12px;margin-top:4px;">'
                f'... and {len(fast_movers) - 10} more</div>'
            )
        mover_html += "</div>"
        st.markdown(mover_html, unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # AI Market Briefing
    # -----------------------------------------------------------------------

    with st.spinner("Generating AI market briefing..."):
        ai_brief = generate_ai_market_brief(new_contenders, fast_movers)

    if ai_brief:
        brief_html = '<div class="ai-brief">'
        brief_html += "<h3>AI Market Briefing</h3>"
        brief_html += f"<div>{ai_brief}</div>"
        brief_html += "</div>"
        st.markdown(brief_html, unsafe_allow_html=True)
    elif CLAUDE_API_KEY:
        # API key is set but no brief was generated (no data to analyze)
        pass
    else:
        st.caption(
            "AI market briefing requires CLAUDE_API_KEY environment variable. "
            "Set it to enable AI-powered analysis."
        )

    st.divider()

# ---------------------------------------------------------------------------
# Section 1: Competitor Highlights (st.metric)
# ---------------------------------------------------------------------------

st.subheader("Core Competitor Performance")

cols = st.columns(len(COMPETITORS))
for idx, (comp_name, comp_info) in enumerate(COMPETITORS.items()):
    app_id = str(comp_info["app_id"])
    rank = get_competitor_rank(today_ranking, app_id)

    with cols[idx]:
        if rank is not None:
            delta_val = compute_delta(
                history, today_key, yesterday_key, app_id, rank
            )
            delta_str = None
            if delta_val is not None:
                if delta_val > 0:
                    delta_str = f"+{delta_val}"
                elif delta_val < 0:
                    delta_str = str(delta_val)
                else:
                    delta_str = "0"

            st.metric(
                label=comp_name,
                value=f"#{rank}",
                delta=delta_str,
            )
        else:
            st.metric(
                label=comp_name,
                value="N/A",
                delta=None,
            )

st.divider()

# ---------------------------------------------------------------------------
# Section 2: Full Top 100 Table
# ---------------------------------------------------------------------------

st.subheader("Full Leaderboard")

# Build table data
table_data = []
for app in today_ranking:
    app_id = app["app_id"]
    name = app["name"]
    rank = app["rank"]

    delta_val = compute_delta(history, today_key, yesterday_key, app_id, rank)
    delta_str = ""
    if delta_val is not None:
        if delta_val > 0:
            delta_str = f"+{delta_val}"
        elif delta_val < 0:
            delta_str = str(delta_val)
        else:
            delta_str = "0"

    is_known = is_known_app(known_apps, app_id, name)
    known_label = "Yes" if is_known else ""

    table_data.append(
        {
            "Rank": rank,
            "App Name": name,
            "Rank Change": delta_str,
            "Known Competitor": known_label,
        }
    )

st.dataframe(
    table_data,
    width="stretch",
    hide_index=True,
    column_config={
        "Rank": st.column_config.NumberColumn(width="small"),
        "App Name": st.column_config.TextColumn(width="large"),
        "Rank Change": st.column_config.TextColumn(
            width="small",
            help="Positive = moved up, Negative = moved down",
        ),
        "Known Competitor": st.column_config.TextColumn(width="medium"),
    },
)

# ---------------------------------------------------------------------------
# Section 3: History Stats
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Data Collection Stats")

total_days = len(history)
st.caption(f"Days of ranking history collected: {total_days}")
st.caption(f"Latest snapshot: {today_key}")

# Show yesterday's data availability
if yesterday_key in history:
    yesterday_count = len(history[yesterday_key])
    st.caption(f"Yesterday ({yesterday_key}): {yesterday_count} apps recorded")
else:
    st.caption(f"Yesterday ({yesterday_key}): No data available")

# Export JSON for dashboard (with multi-source data)
with st.spinner("Collecting multi-source data..."):
    records = aggregate_market_data(COMPETITORS)
    save_market_csv(records)
    multi_source_data = {rec["app"]: {
        "rank": rec.get("rank"),
        "download_proxy": rec.get("download_proxy"),
        "rating_growth": rec.get("rating_growth"),
        "revenue_proxy": rec.get("revenue_proxy"),
        "sentiment_score": rec.get("sentiment_score"),
        "update_frequency": rec.get("update_frequency"),
        "timestamp": rec.get("timestamp"),
        "_raw": rec.get("_raw", {}),
    } for rec in records}
export_json(today_ranking, history, known_apps, new_contenders, fast_movers, ai_brief if 'ai_brief' in locals() else None, multi_source_data)
