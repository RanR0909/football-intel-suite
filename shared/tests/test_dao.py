#!/usr/bin/env python3
"""DAO 单测：SQLite in-memory 跑 schema，不依赖真实 MySQL。

覆盖：
- bulk_insert_reviews
- upsert_ad_creatives（同 ad_id 二次插入只刷新）
- bulk_insert_iap + price 解析
- bulk_insert_rank_snapshots
- upsert_community_posts
- append_sync_log
- DAO 层 graceful degrade（MYSQL_DSN 未配置 → 全部 return 0）

运行：
    python3 -m shared.tests.test_dao
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _check(name, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"  {status} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        raise AssertionError(name)


def _setup_sqlite():
    """配置 in-memory SQLite + 建表 + seed 1 个 competitor。"""
    os.environ["MYSQL_DSN"] = "sqlite:///:memory:"
    os.environ.pop("REDIS_URL", None)

    from shared import db as _db
    from shared import models, dao
    _db.reset_for_test()
    dao.clear_competitor_cache()

    eng = _db.engine()
    models.Base.metadata.create_all(eng)

    # seed 1 competitor + 1 region
    with _db.session() as s:
        s.add(models.Competitor(name="SofaScore", gp_package="com.sofascore.results",
                                ios_app_id="1176147574", bundle_id="com.SofaScore.iOS"))
        s.add(models.Region(code="us", label="美国", lang="en"))


def run_tests():
    print("=== 0. graceful degrade（无 DSN）===")
    os.environ.pop("MYSQL_DSN", None)
    from shared import db as _db
    _db.reset_for_test()
    from shared.dao import reviews as dao_reviews
    n = dao_reviews.bulk_insert_reviews("SofaScore", "us", [{"score": 5, "content": "x"}])
    _check("MYSQL_DSN 未配置 → return 0", n == 0)

    print("\n=== 1. bulk_insert_reviews ===")
    _setup_sqlite()
    from shared.dao import reviews as dao_reviews
    rows = [
        {"score": 5, "version": "1.0", "content": "great", "_platform": "gp"},
        {"score": 2, "version": "1.0", "content": "buggy", "_platform": "ios"},
    ]
    n = dao_reviews.bulk_insert_reviews("SofaScore", "us", rows)
    _check("插入 2 条 reviews", n == 2)

    from shared import db as _db, models
    with _db.session() as s:
        cnt = s.query(models.Review).count()
        _check("DB 内 reviews 数 = 2", cnt == 2)
        rev = s.query(models.Review).filter(models.Review.platform == "gp").first()
        _check("platform=gp 的 score 透传", rev.score == 5)

    # 未知 competitor
    n2 = dao_reviews.bulk_insert_reviews("UnknownApp", "us", rows)
    _check("未知 competitor → 跳过 return 0", n2 == 0)

    print("\n=== 2. upsert_ad_creatives 去重 ===")
    from shared.dao import ads as dao_ads
    ads = [
        {"ad_id": "a1", "text": "live scores", "start_date": "2026-04-01"},
        {"ad_id": "a2", "text": "VIP unlock"},
    ]
    n = dao_ads.upsert_ad_creatives("SofaScore", "us", ads)
    _check("第一次插 2 条", n == 2)
    # 同 ad_id 再插（一条变更）
    ads2 = [{"ad_id": "a1", "text": "live scores UPDATED", "start_date": "2026-04-15"}]
    n = dao_ads.upsert_ad_creatives("SofaScore", "us", ads2)
    _check("UPSERT 同 ad_id 返回 1", n == 1)
    with _db.session() as s:
        cnt = s.query(models.AdCreative).count()
        _check("总条数仍 2（去重）", cnt == 2)
        a1 = s.query(models.AdCreative).filter(models.AdCreative.ad_id == "a1").first()
        _check("text 已刷新", a1.text == "live scores UPDATED")

    print("\n=== 3. bulk_insert_iap + price 解析 ===")
    from shared.dao import iap as dao_iap
    items = [
        {"name": "Premium", "price": "$9.99", "currency": "USD", "category": "subscription"},
        {"name": "Coins x100", "price": "￥68", "currency": "CNY"},
        {"name": "Bad", "price": None, "currency": None},
    ]
    n = dao_iap.bulk_insert_iap("SofaScore", "us", items)
    _check("插入 3 条 IAP", n == 3)
    with _db.session() as s:
        rows = s.query(models.IapItem).order_by(models.IapItem.name).all()
        from decimal import Decimal
        prices = {r.name: r.price_num for r in rows}
        _check("price_num 解析: Premium=9.99",
               prices.get("Premium") == Decimal("9.99"),
               detail=f"got {prices.get('Premium')}")
        _check("price_num 解析: Coins=68",
               prices.get("Coins x100") == Decimal("68"),
               detail=f"got {prices.get('Coins x100')}")
        _check("price_num 解析: Bad=None", prices.get("Bad") is None)

    print("\n=== 4. bulk_insert_rank_snapshots ===")
    from shared.dao import rank as dao_rank
    rows = [
        {"name": "SofaScore", "competitor": "SofaScore", "region": "us",
         "rank": 5, "delta": -2, "downloads": "~10K"},
        {"name": "RandomApp", "competitor": None, "region": "us",
         "rank": 7, "delta": 1, "downloads": "~5K"},
        {"name": "SofaScore", "competitor": "SofaScore", "region": None,
         "rank": 12, "delta": 0, "downloads": "~50K"},
    ]
    n = dao_rank.bulk_insert_rank_snapshots("appmagic", rows)
    _check("插入 3 条 rank snapshots", n == 3)
    with _db.session() as s:
        cnt = s.query(models.MarketRankSnapshot).count()
        _check("DB 内 3 条", cnt == 3)
        ww = s.query(models.MarketRankSnapshot).filter(
            models.MarketRankSnapshot.region_code.is_(None)).first()
        _check("worldwide 行的 region_code = NULL", ww is not None and ww.region_code is None)
        unmapped = s.query(models.MarketRankSnapshot).filter(
            models.MarketRankSnapshot.competitor_id.is_(None)).first()
        _check("非 tracked 应用 competitor_id = NULL", unmapped is not None)

    print("\n=== 5. upsert_community_posts 去重 ===")
    from shared.dao import community as dao_comm
    posts = [
        {"post_id": "p1", "subreddit": "soccer", "title": "title 1",
         "score": 100, "num_comments": 10, "url": "https://...", "created_utc": 1700000000},
    ]
    n = dao_comm.upsert_community_posts("SofaScore", "reddit", posts)
    _check("第一次插 1 条", n == 1)
    posts2 = [{"post_id": "p1", "title": "UPDATED", "score": 200, "num_comments": 50}]
    dao_comm.upsert_community_posts("SofaScore", "reddit", posts2)
    with _db.session() as s:
        cnt = s.query(models.CommunityPost).count()
        _check("总条数仍 1（UPSERT）", cnt == 1)
        p = s.query(models.CommunityPost).first()
        _check("score 已刷新到 200", p.score == 200)

    print("\n=== 6. append_sync_log ===")
    from shared.dao import sync_log as dao_log
    entry = {
        "script": "comment_label",
        "label": "评论 AI 标签",
        "competitor": None,
        "started_at": "2026-04-28T10:00:00",
        "finished_at": "2026-04-28T10:12:34",
        "duration_sec": 754.0,
        "success": True,
        "error_kind": None,
        "stdout_tail": "ok",
        "stderr_tail": "",
        "cmd": "python3 ...",
    }
    ok = dao_log.append_sync_log(entry)
    _check("append_sync_log 返回 True", ok is True)
    with _db.session() as s:
        cnt = s.query(models.SyncLog).count()
        _check("DB 内 sync_log 数 = 1", cnt == 1)
        entry_db = s.query(models.SyncLog).first()
        _check("script 字段透传", entry_db.script == "comment_label")
        _check("success 字段透传", entry_db.success is True)

    print("\n🎉 DAO 全部断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
