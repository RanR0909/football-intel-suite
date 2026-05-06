#!/usr/bin/env python3
"""SiteData (sitedata.dev) 流量 API 抓取 — 替代 similarweb 直抓。

为什么换：similarweb.com 公开页是 CloudFront 防护的，server 端 IP 直接 403。
SiteData 是个 Chrome 扩展（emeakbgdecgmdjgegnejpppcnkcnoaen），它自己做 server-side
similarweb scraping 然后把数据透出给注册用户。一次注册（免费）→ 永久 client UUID
→ JSON API 直取。

CLI:
    python3 -m market_rank.scrape_sitedata               # 抓所有 website 竞品
    python3 -m market_rank.scrape_sitedata --domain X    # 只抓一个

环境变量：
    SITEDATA_UUID   注册用户 uuid（必需）

API:
    GET https://traffic.<rotating-host>/?
        domain=X&timestamp=MS&source=extension&clientId=UUID
        &sign=SHA256(UUID + MS + secret)[:32]
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

from competitors import get_website_competitors  # type: ignore
from shared.dao import website_traffic as dao_traffic  # type: ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scrape_sitedata")

DATA_OUT = _PROJECT_ROOT / "data" / "async_sitedata.json"
RAW_OUT_DIR = _PROJECT_ROOT / "data" / "raw"

# 17 个 traffic.* 主机轮询，与扩展行为一致（避免单主机限流）
TRAFFIC_HOSTS = [
    "https://traffic.sitedata.dev",
    "https://traffic.gempix.cc",
    "https://traffic.peakwiki.cc",
    "https://traffic.workfast.cc",
    "https://traffic.newtoki.cc",
    "https://traffic.bratgenerator.top",
    "https://traffic.brainrot.sh",
    "https://traffic.growagardenscript.vip",
    "https://traffic.99nightsintheforest.xyz",
    "https://traffic.pubidlookup.com",
    "https://traffic.youtubetranscript.xyz",
    "https://traffic.mangatrans.io",
    "https://traffic.mangatranslator.vip",
    "https://traffic.myip.cafe",
    "https://traffic.chathub.dev",
    "https://traffic.facetomany.xyz",
    "https://traffic.gachiakuta.co",
]

SECRET = "2@3&^8d4$%H9,M"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
REQUEST_INTERVAL_SEC = 0.5  # 与扩展 requestInterval 一致


def _sign(uuid: str, ts: str) -> str:
    return hashlib.sha256((uuid + ts + SECRET).encode()).hexdigest()[:32]


def _fmt_visits_short(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1e9:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n / 1e3:.1f}K"
    return str(n)


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fetch_one(domain: str, uuid: str, host_iter) -> dict | None:
    """单域名抓取。host_iter 是 itertools.cycle(TRAFFIC_HOSTS)，跨调用复用以做轮询。"""
    host = next(host_iter)
    ts = str(int(time.time() * 1000))
    sign = _sign(uuid, ts)
    qs = urllib.parse.urlencode({
        "domain": domain,
        "timestamp": ts,
        "source": "extension",
        "clientId": uuid,
        "sign": sign,
    })
    url = f"{host}/?{qs}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        log.warning(f"[{domain}] HTTP {e.code} via {host}: {body}")
        return None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as e:
        log.warning(f"[{domain}] fetch via {host} failed: {e}")
        return None


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_response(domain: str, data: dict) -> tuple[date, dict] | None:
    """SiteData JSON → upsert payload。返回 (snapshot_month, payload)，无效数据返回 None。"""
    if not isinstance(data, dict):
        return None
    eng = data.get("Engagments") or {}
    visits = _to_int(eng.get("Visits"))
    if not visits:
        log.info(f"[{domain}] 无 Visits 数据")
        return None

    # snapshot_month: 用 API 返回的 Year/Month，回退到当月
    y = _to_int(eng.get("Year"))
    m = _to_int(eng.get("Month"))
    today = date.today()
    if y and m and 1 <= m <= 12 and 2020 <= y <= 2100:
        snapshot_month = date(y, m, 1)
    else:
        snapshot_month = today.replace(day=1)

    duration_sec = _to_int(eng.get("TimeOnSite"))
    pages = _to_float(eng.get("PagePerVisit"))
    bounce = _to_float(eng.get("BounceRate"))

    global_rank = None
    gr = data.get("GlobalRank")
    if isinstance(gr, dict):
        global_rank = _to_int(gr.get("Rank"))

    category_rank = None
    category_rank_country = None
    cr = data.get("CategoryRank")
    if isinstance(cr, dict):
        category_rank = _to_int(cr.get("Rank")) or None
        cat = (cr.get("Category") or "").strip() or None
        if cat:
            category_rank_country = cat[:64]

    top_countries = []
    for entry in (data.get("TopCountryShares") or [])[:5]:
        if isinstance(entry, dict):
            top_countries.append({
                "country": entry.get("CountryCode"),
                "share": _to_float(entry.get("Value")),
            })

    similar_sites = []
    comp_block = data.get("Competitors") or {}
    for entry in (comp_block.get("TopSimilarityCompetitors") or [])[:5]:
        if isinstance(entry, dict):
            similar_sites.append({
                "domain": entry.get("Domain") or entry.get("Name"),
                "score": _to_float(entry.get("Score")),
            })

    payload = {
        "monthly_visits": _fmt_visits_short(visits),
        "monthly_visits_num": visits,
        "avg_visit_duration": _fmt_duration(duration_sec) if duration_sec else None,
        "avg_visit_duration_sec": duration_sec,
        "pages_per_visit": pages,
        "bounce_rate": bounce,
        "global_rank": global_rank,
        "category_rank": category_rank,
        "country_rank_country": category_rank_country,
        "top_countries": top_countries or None,
        "similar_sites": similar_sites or None,
        "raw_text": json.dumps(data, ensure_ascii=False)[:8000],
    }
    return snapshot_month, payload


def run(only_domain: str | None = None) -> int:
    uuid = os.environ.get("SITEDATA_UUID", "").strip()
    if not uuid:
        log.error("缺少 SITEDATA_UUID 环境变量（在 .env.local 里设）")
        return 2

    competitors = get_website_competitors()
    if only_domain:
        competitors = {n: d for n, d in competitors.items() if d == only_domain}
        if not competitors:
            log.error(f"--domain {only_domain} 不在 competitors.json")
            return 2

    log.info(f"将抓取 {len(competitors)} 个域名")
    host_iter = itertools.cycle(TRAFFIC_HOSTS)

    raw_dump = {"fetched_at": datetime.now(timezone.utc).isoformat(), "results": {}}
    written = 0
    failed: list[str] = []

    for i, (name, domain) in enumerate(competitors.items()):
        log.info(f"[{i+1}/{len(competitors)}] {name} → {domain}")
        if i > 0:
            time.sleep(REQUEST_INTERVAL_SEC)
        data = fetch_one(domain, uuid, host_iter)
        if not data:
            failed.append(f"{name}({domain}):no_response")
            continue
        if data.get("code") == 403 or data.get("error"):
            log.warning(f"[{domain}] API error: {data.get('error') or data}")
            failed.append(f"{name}({domain}):api_error")
            continue
        raw_dump["results"][name] = data
        parsed = parse_response(domain, data)
        if not parsed:
            failed.append(f"{name}({domain}):no_data")
            continue
        snapshot_month, payload = parsed
        n = dao_traffic.upsert_website_traffic(
            competitor_name=name,
            domain=domain,
            snapshot_month=snapshot_month,
            payload=payload,
        )
        if n:
            written += 1
            log.info(
                f"  ✓ {payload['monthly_visits']} visits / {snapshot_month} "
                f"(rank={payload.get('global_rank')})"
            )
        else:
            failed.append(f"{name}({domain}):upsert_skip")

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(raw_dump, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info(f"完成：写入 {written}/{len(competitors)}（失败 {len(failed)}）")
    if failed:
        log.warning("失败详情：%s", failed)
    return 0 if written > 0 else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--domain", help="只抓单个域名（必须在 competitors.json 里）")
    args = p.parse_args()
    sys.exit(run(only_domain=args.domain))


if __name__ == "__main__":
    main()
