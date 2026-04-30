"""自动发现 peer 候选 — 基于 appstore_rank top 100 + app_classifier 任务（AI v2）。

⚠️ **严格分离**：candidate **永远不会** 自动写入 `competitors` 表 / `competitors.json`。
   所有候选只入 `app_classifications` 表（独立的"候选池"），人工查 SQL 选择是否手工
   迁移到 competitors。

流程：
  1. 读 data/async_appstore_rank.json（最近一次 appstore_rank 抓取的 top 100）
  2. 过滤：跳过已在 competitors.json 里的 app（按 iOS app_id 匹配 — 避免重复评估自己人）
  3. 对每个 unknown app：
       a. 30 天缓存命中 → 直接读 app_classifications（不调 AI）
       b. 否则 iTunes Lookup API 取 description / publisher
       c. 调 ai_tasks.app_classifier.classify_app（→ 存 app_classifications 表）
  4. 列出符合「peer 候选」门槛的 app（is_relevant=true + topic ∈ {football, multi_sport} + conf ≥ 阈值）

CLI:
    python3 -m ai_tasks.discover_peers                         # 跑分类（默认 limit=None = 所有 unknown）
    python3 -m ai_tasks.discover_peers --limit 20              # 限制处理 20 个
    python3 -m ai_tasks.discover_peers --min-confidence 0.9    # 提高入选门槛
    python3 -m ai_tasks.discover_peers --topic football        # 只列 football 候选
    python3 -m ai_tasks.discover_peers list                    # 不抓，仅列出当前 candidates
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


def discover(
    *,
    limit: int | None = None,
    min_confidence: float = 0.85,
    target_topics: set[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """扫 unknown apps 并分类入 app_classifications；候选仅在结果里展示，不写 competitors。"""
    target_topics = target_topics or {"football", "multi_sport"}
    unknowns = _load_unknown_apps_from_rankings(limit=limit)
    log.info(f"unknown apps to evaluate: {len(unknowns)}")

    summary = {
        "total_unknown": len(unknowns),
        "classified": 0,
        "cached": 0,
        "errors": 0,
        "candidates": [],          # peer 候选（满足 topic + confidence 门槛 — 仅列出，不写 competitors）
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

        # 评估 peer 候选门槛 — 只判定 + 列出，不写 competitors
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
            f"  ⭐ candidate: {app['name']:40s} topic={topic:12s} "
            f"conf={conf:.2f} cats={cand['categories']}"
        )

    summary["duration_sec"] = round(time.monotonic() - t0, 1)
    return summary


def list_candidates(
    *,
    min_confidence: float = 0.85,
    target_topics: set[str] | None = None,
    include_already_tracked: bool = False,
) -> list[dict]:
    """从 app_classifications 表查满足门槛的 candidate。

    默认排除已经在 competitors.json 里的 app（candidate 的语义 = 尚未跟踪的潜在 peer）。
    传 include_already_tracked=True 可以同时看已跟踪的（debug 用）。
    """
    target_topics = target_topics or {"football", "multi_sport"}
    known = _known_ios_ids()
    out: list[dict] = []
    for r in dao_class.list_relevant():
        if r.get("topic") not in target_topics:
            continue
        if (r.get("confidence") or 0) < min_confidence:
            continue
        if not include_already_tracked and str(r.get("app_id") or "") in known:
            continue
        out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subcommand", nargs="?", default="scan",
                    choices=["scan", "list"],
                    help="scan = 抓 + 分类 + 列候选（默认）；list = 不抓只列已存的候选")
    ap.add_argument("--limit", type=int, default=None,
                    help="scan 模式下处理多少 unknown app（默认全部）")
    ap.add_argument("--min-confidence", type=float, default=0.85)
    ap.add_argument("--topic", action="append", choices=sorted(VALID_TOPICS),
                    help="目标 topic（可重复）；不传 = football + multi_sport")
    ap.add_argument("--dry-run", action="store_true",
                    help="不调 AI、不入库 — 只打印将会处理多少 app（仅 scan）")
    ap.add_argument("--include-already-tracked", action="store_true",
                    help="list 模式下，连已在 competitors.json 里的也一起列（debug 用）")
    args = ap.parse_args()

    target_topics = set(args.topic) if args.topic else {"football", "multi_sport"}

    if args.subcommand == "list":
        cands = list_candidates(
            min_confidence=args.min_confidence,
            target_topics=target_topics,
            include_already_tracked=args.include_already_tracked,
        )
        print(json.dumps({
            "candidates": cands,
            "count": len(cands),
            "filters": {
                "min_confidence": args.min_confidence,
                "topics": sorted(target_topics),
            },
        }, ensure_ascii=False, indent=2))
        return 0

    summary = discover(
        limit=args.limit,
        min_confidence=args.min_confidence,
        target_topics=target_topics,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
