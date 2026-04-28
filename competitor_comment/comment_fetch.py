#!/usr/bin/env python3
"""comment_fetch.py — 仅抓 GP + iOS 评论（无 AI），落盘到 data/raw/comments_raw.json

P0 拆分：原 auto_report.py 把抓取 + AI 标签 + 摘要写在一起，导致 AI 慢就连带把抓
到的评论一起丢掉。把抓取部分独立，能保证：
- 抓取耗时 ~60s（可控）
- 失败/AI 挂掉不影响下一次直接对 raw 重跑标签
- comment_label.py 只读这个 raw 文件

输出 shape：
{
  "generated_at": "...",
  "date": "YYYY-MM-DD",
  "cutoff_days": 3,
  "competitors": {
    "<name>": {
      "regions": {
        "<region>": {
          "rows": [{score, version, content, _platform: "gp"|"ios"}, ...]
        }
      }
    }
  }
}
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from google_play_scraper import reviews, Sort

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_OUT = RAW_DIR / "comments_raw.json"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from competitors import get_comment_competitors  # type: ignore
from regions import get_region_codes, load_regions  # type: ignore
from shared.dao import reviews as dao_reviews  # type: ignore

FETCH_COUNT = 200
CUTOFF_DAYS = 3


def fetch_gp(pkg: str, country: str, lang: str) -> list[dict]:
    """Google Play 评论（near real-time）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
    try:
        result, _ = reviews(pkg, lang=lang, country=country, sort=Sort.NEWEST, count=FETCH_COUNT)
    except Exception as e:
        print(f"    [GP][{pkg}/{country}] 抓取失败: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    if not result:
        print(
            f"    [GP][{pkg}/{country}] 警告：返回 0 条 — 通常是包名 {pkg!r} 在 Google Play 不存在。",
            file=sys.stderr,
        )
    rows = []
    for r in result:
        at = r["at"].replace(tzinfo=timezone.utc) if r["at"].tzinfo is None else r["at"]
        if at >= cutoff:
            rows.append({
                "score": r["score"],
                "version": r.get("appVersion", "") or "",
                "content": r["content"] or "",
                "_platform": "gp",
            })
    return rows


def fetch_ios(app_id, country: str) -> list[dict]:
    """iOS 评论 — 沿用 auto_report.py 行为：

    1. 优先 app-store-scraper（基于 Apple 内部 customer-reviews JSON）
    2. fallback 老 RSS（Apple 已弃用，多数情况 0 条）

    Apple 全球反爬严格，常返 [] — 可接受，由 GP 兜底。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
    # 主路径
    try:
        from app_store_scraper import AppStore
        scraper = AppStore(country=country, app_name=str(app_id), app_id=int(app_id))
        scraper.review(how_many=FETCH_COUNT, sleep=1)
        rows = []
        for r in scraper.reviews or []:
            ts = r.get("date")
            if ts:
                if not getattr(ts, "tzinfo", None):
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            rows.append({
                "score": int(r.get("rating") or 5),
                "version": r.get("version") or "",
                "content": (r.get("review") or r.get("title") or "").strip(),
                "_platform": "ios",
            })
        return rows
    except Exception as e:
        print(f"    [iOS][{app_id}/{country}] app-store-scraper 失败 ({type(e).__name__}: {e})，降级 RSS",
              file=sys.stderr)

    # Fallback RSS（多数情况空）
    rows, page = [], 1
    while len(rows) < FETCH_COUNT and page <= 10:
        url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
        except Exception:
            break
        entries = data.get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list) or not entries:
            break
        start_idx = 1 if entries and isinstance(entries[0], dict) and "im:name" in entries[0] else 0
        for e in entries[start_idx:]:
            score = int(e.get("im:rating", {}).get("label", 5))
            rows.append({
                "score": score,
                "version": e.get("im:version", {}).get("label", ""),
                "content": e.get("content", {}).get("label", ""),
                "_platform": "ios",
            })
        page += 1
    return rows


def main() -> Path:
    competitors = get_comment_competitors()
    regions = get_region_codes()
    region_info = load_regions()

    out = {
        "generated_at": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "cutoff_days": CUTOFF_DAYS,
        "competitors": {},
    }

    total_rows = 0
    total_db = 0
    for app_name, comp in competitors.items():
        app_data = {"regions": {}}
        for region in regions:
            lang = region_info.get(region, {}).get("lang", "en")
            print(f"[{app_name}/{region}] 抓取（GP+iOS）...")
            gp_rows = fetch_gp(comp["gp"], region, lang)
            ios_rows = fetch_ios(comp["ios"], region)
            rows = gp_rows + ios_rows
            app_data["regions"][region] = {"rows": rows}
            total_rows += len(rows)
            # 双写 MySQL（DB 不可用时静默跳过）
            db_n = dao_reviews.bulk_insert_reviews(app_name, region, rows)
            total_db += db_n
            print(f"  -> GP={len(gp_rows)}  iOS={len(ios_rows)}  合计={len(rows)}  DB+{db_n}")
        out["competitors"][app_name] = app_data

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 评论 raw 已保存 -> {RAW_OUT}（{len(competitors)} 竞品 × {len(regions)} 区，共 {total_rows} 条；MySQL 写入 {total_db} 条）")
    return RAW_OUT


if __name__ == "__main__":
    main()
