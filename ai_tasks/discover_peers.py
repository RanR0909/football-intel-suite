"""自动发现新 peer — 基于 appstore_rank top 100 + app_classifier 任务（AI v2）。

流程：
  1. 读 data/async_appstore_rank.json（最近一次 appstore_rank 抓取的 top 100）
  2. 过滤：跳过已在 competitors.json 里的 app（按 iOS app_id 匹配）
  3. 对每个 unknown app：
       a. 跳过最近 30 天已分类的（app_classifications 缓存）
       b. iTunes Lookup API 取 description / publisher
       c. 调 ai_tasks.app_classifier.classify_app（→ 存 app_classifications 表）
  4. 列出符合「peer 候选」的 app（is_relevant=true + topic ∈ {football, multi_sport} + conf ≥ 阈值）
  5. 可选：--auto-promote 自动加到 competitors lookup（默认关闭，避免污染人工 curation）

CLI:
    python3 -m ai_tasks.discover_peers                         # 全跑（dry-classify 模式，只入 app_classifications）
    python3 -m ai_tasks.discover_peers --limit 20              # 限制处理 20 个
    python3 -m ai_tasks.discover_peers --auto-promote          # 自动加高置信 peer 到 competitors
    python3 -m ai_tasks.discover_peers --min-confidence 0.9    # 提高入选门槛
    python3 -m ai_tasks.discover_peers --topic football        # 只看 football peer
"""

from __future__ import annotations

import argparse
import json
import logging
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

from competitors import load_competitors  # noqa: E402
from shared.dao import app_classifications as dao_class  # noqa: E402
from ai_tasks.app_classifier import classify_app, VALID_TOPICS  # noqa: E402

log = logging.getLogger("discover_peers")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s · %(message)s")

APPSTORE_RANK_JSON = _PROJECT_ROOT / "data" / "async_appstore_rank.json"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
LOOKUP_TIMEOUT = 8
LOOKUP_RATE_DELAY = 0.5   # iTunes 限频 ~20 req/s 但我们只跑 ~100 条 / 天，慢点稳一点


# ---- iTunes Lookup ---------------------------------------------------------


def _ssl_ctx_no_verify() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_metadata_ios(app_id: str) -> dict | None:
    """返回 {name, publisher, description, category, bundle_id} 或 None。"""
    if not app_id:
        return None
    url = f"{ITUNES_LOOKUP}?id={urllib.parse.quote(str(app_id))}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FootballIntelBot/1.0"})
        with urllib.request.urlopen(req, timeout=LOOKUP_TIMEOUT, context=_ssl_ctx_no_verify()) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        log.warning(f"iTunes lookup {app_id} failed: {e}")
        return None
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]
    return {
        "name": r.get("trackName") or "",
        "publisher": r.get("sellerName") or "",
        "description": r.get("description") or "",
        "category": r.get("primaryGenreName") or "",
        "bundle_id": r.get("bundleId") or "",
    }


# ---- 主流程 ---------------------------------------------------------------


def _known_ios_ids() -> set[str]:
    """data/competitors.json 里所有 iOS app_id（含 baseline）。"""
    out: set[str] = set()
    for entry in load_competitors().values():
        for k in ("ios", "app_id"):
            v = entry.get(k)
            if v:
                out.add(str(v))
    return out


def _load_unknown_apps_from_rankings(*, limit: int | None = None) -> list[dict]:
    """读 async_appstore_rank.json，过滤掉已知 app（按 ios app_id）"""
    if not APPSTORE_RANK_JSON.exists():
        log.warning(f"{APPSTORE_RANK_JSON} 不存在 — 请先跑 appstore_rank 抓取")
        return []
    payload = json.loads(APPSTORE_RANK_JSON.read_text(encoding="utf-8"))
    known = _known_ios_ids()
    unknowns: list[dict] = []
    seen: set[str] = set()
    for rec in payload:
        d = rec.get("data") or {}
        aid = str(d.get("app_id") or "").strip()
        if not aid or aid in known or aid in seen:
            continue
        seen.add(aid)
        unknowns.append({
            "app_id": aid,
            "name": rec.get("competitor") or "",
            "bundle_id": d.get("bundle_id") or "",
            "category": d.get("category") or "Sports",
            "rank": d.get("rank"),
        })
        if limit and len(unknowns) >= limit:
            break
    return unknowns


def _promote_to_competitors(name: str, bundle_id: str, app_id: str) -> bool:
    """把发现的 peer 写入 MySQL competitors 表 + competitors.json。

    重复（同名 / 同 app_id）幂等：检测到已存在直接跳过。

    NOTE：对 competitors.json 的写入是文件级 mutate；目前不加 file lock，因为
    discover_peers 默认每天 1 次，不会有并发。
    """
    from shared import db as _db
    from sqlalchemy import text
    if not _db.is_mysql_enabled():
        log.warning("MYSQL_DSN 未配置，跳过 promote")
        return False

    # 1) MySQL competitors 表
    with _db.session() as s:
        existing = s.execute(text(
            "SELECT id FROM competitors WHERE name = :n OR ios_app_id = :a LIMIT 1"
        ), {"n": name, "a": app_id}).first()
        if existing:
            log.info(f"  competitors.id={existing.id} 已存在，跳过")
            return False
        s.execute(text(
            "INSERT INTO competitors (name, gp_package, ios_app_id, bundle_id, created_at) "
            "VALUES (:name, NULL, :ios, :bid, NOW())"
        ), {"name": name[:64], "ios": app_id[:32], "bid": (bundle_id or "")[:128] or None})
        log.info(f"  ✓ competitors 表 INSERT: {name}")

    # 2) competitors.json
    cj = _PROJECT_ROOT / "data" / "competitors.json"
    try:
        data = json.loads(cj.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if name in data:
        log.info(f"  competitors.json 已含 {name}，跳过 JSON 写入")
        return True
    data[name] = {
        "ios": int(app_id) if app_id.isdigit() else app_id,
        "app_id": app_id,
        "bundle_id": bundle_id or "",
        "is_discovered": True,                # 标记 AI 自动发现的 peer，便于人工审核
        "_doc": "由 ai_tasks.discover_peers 自动添加 — 人工核对后可去掉 is_discovered",
    }
    cj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"  ✓ competitors.json 写入: {name}")
    return True


def discover(
    *,
    limit: int | None = None,
    min_confidence: float = 0.85,
    target_topics: set[str] | None = None,
    auto_promote: bool = False,
    dry_run: bool = False,
) -> dict:
    target_topics = target_topics or {"football", "multi_sport"}
    unknowns = _load_unknown_apps_from_rankings(limit=limit)
    log.info(f"unknown apps to evaluate: {len(unknowns)}")

    summary = {
        "total_unknown": len(unknowns),
        "classified": 0,
        "cached": 0,
        "errors": 0,
        "candidates": [],          # peer 候选（满足 topic + confidence 门槛）
        "promoted": [],            # 已 auto-promote
        "rejected_low_conf": 0,
        "rejected_off_topic": 0,
        "rejected_irrelevant": 0,
    }
    t0 = time.monotonic()

    for app in unknowns:
        aid = app["app_id"]
        if dao_class.is_already_classified(aid, "ios", max_age_days=30):
            cached = dao_class.get(aid, "ios")
            summary["cached"] += 1
            log.info(f"  [cached] {app['name']} → topic={cached.get('topic')}")
            class_out = cached
        else:
            if dry_run:
                log.info(f"  [dry] would classify {app['name']} (id={aid})")
                continue
            # iTunes Lookup
            meta = fetch_metadata_ios(aid)
            time.sleep(LOOKUP_RATE_DELAY)
            if not meta:
                summary["errors"] += 1
                continue
            class_out = classify_app(
                app_id=aid,
                platform="ios",
                name=meta["name"] or app["name"],
                publisher=meta["publisher"],
                description=meta["description"],
                category=meta["category"] or app["category"],
                matched_keywords=["sports"],   # 都是从 sports top 100 来的
                skip_if_recent=False,           # 已在外层判过
                persist=True,
            )
            if class_out.get("error"):
                summary["errors"] += 1
                log.warning(f"  [err] {app['name']}: {class_out.get('error')}")
                continue
            summary["classified"] += 1

        # 评估 peer 候选门槛
        is_rel = bool(class_out.get("is_relevant"))
        topic = class_out.get("topic") or ""
        conf = float(class_out.get("confidence") or 0)
        if not is_rel:
            summary["rejected_irrelevant"] += 1
            continue
        if topic not in target_topics:
            summary["rejected_off_topic"] += 1
            continue
        if conf < min_confidence:
            summary["rejected_low_conf"] += 1
            continue

        # 是 candidate
        cand = {
            "app_id": aid,
            "name": app["name"],
            "bundle_id": app["bundle_id"],
            "topic": topic,
            "categories": class_out.get("categories") or [],
            "confidence": conf,
            "rank": app.get("rank"),
        }
        summary["candidates"].append(cand)
        log.info(
            f"  ⭐ peer candidate: {app['name']:40s} topic={topic:12s} "
            f"conf={conf:.2f} cats={cand['categories']}"
        )
        if auto_promote and not dry_run:
            ok = _promote_to_competitors(app["name"], app["bundle_id"], aid)
            if ok:
                summary["promoted"].append(cand)

    summary["duration_sec"] = round(time.monotonic() - t0, 1)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-confidence", type=float, default=0.85)
    ap.add_argument("--topic", action="append", choices=sorted(VALID_TOPICS),
                    help="目标 topic（可重复）；不传 = football + multi_sport")
    ap.add_argument("--auto-promote", action="store_true",
                    help="自动把高置信 peer 加到 competitors lookup + competitors.json（默认关闭）")
    ap.add_argument("--dry-run", action="store_true",
                    help="不调 AI、不入库 — 只打印将会处理多少 app")
    args = ap.parse_args()

    target_topics = set(args.topic) if args.topic else {"football", "multi_sport"}
    summary = discover(
        limit=args.limit,
        min_confidence=args.min_confidence,
        target_topics=target_topics,
        auto_promote=args.auto_promote,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
