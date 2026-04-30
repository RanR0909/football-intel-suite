"""DAO: website_traffic — Similarweb 公开页快照（每月 1 行 / 竞品）。

调用方：market_rank/scrape_similarweb.py

每月 1 号到 31 号期间抓的数据都归到同一个 (competitor, snapshot_month) row，
重复抓会 UPDATE 同一行（数值随月内变化更新到最新）。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from shared import db as _db
from shared.dao import resolve_competitor_id
from shared.models import WebsiteTraffic

log = logging.getLogger("shared.dao.website_traffic")


def upsert_website_traffic(
    competitor_name: str,
    domain: str,
    snapshot_month: date,
    payload: dict,
) -> int:
    """upsert 一条 (competitor, snapshot_month) 的官网流量数据。

    payload 字段（全可选；None / 缺失就不更新）：
      monthly_visits (str), monthly_visits_num (int)
      avg_visit_duration (str), avg_visit_duration_sec (int)
      pages_per_visit (float), bounce_rate (float)
      desktop_share, mobile_share (float, 0–1)
      direct/search/social/referral/mail/display_share (float, 0–1)
      top_countries (list[dict]), top_keywords (list[dict])
      raw_text (str)

    返回 1（写入 / 更新成功）或 0（跳过 / 失败）。
    """
    if not _db.is_mysql_enabled():
        return 0
    if not competitor_name or not domain or not snapshot_month:
        return 0

    try:
        with _db.session() as s:
            cid = resolve_competitor_id(competitor_name, sess=s)
            if cid is None:
                log.warning(f"[website_traffic] competitor {competitor_name!r} 未在 lookup")
                return 0

            now = datetime.utcnow()
            row = {
                "competitor_id": cid,
                "domain": domain[:128],
                "snapshot_month": snapshot_month,
                "monthly_visits": _trim(payload.get("monthly_visits"), 32),
                "monthly_visits_num": _to_int(payload.get("monthly_visits_num")),
                "avg_visit_duration": _trim(payload.get("avg_visit_duration"), 16),
                "avg_visit_duration_sec": _to_int(payload.get("avg_visit_duration_sec")),
                "pages_per_visit": _to_float(payload.get("pages_per_visit")),
                "bounce_rate": _to_float(payload.get("bounce_rate")),
                # 排名
                "global_rank": _to_int(payload.get("global_rank")),
                "country_rank": _to_int(payload.get("country_rank")),
                "country_rank_country": _trim(payload.get("country_rank_country"), 64),
                "category_rank": _to_int(payload.get("category_rank")),
                # 性别（anonymous tier 显示）
                "male_share": _to_float(payload.get("male_share")),
                "female_share": _to_float(payload.get("female_share")),
                # 长尾
                "top_countries_json": _to_json(payload.get("top_countries")),
                "similar_sites_json": _to_json(payload.get("similar_sites")),
                "raw_text": (payload.get("raw_text") or "")[:8000] or None,
                "fetched_at": now,
            }

            # ORM lookup → UPDATE / INSERT（SQLite 和 MySQL 通用，性能可接受 — 9 行 / 周）
            existing = s.query(WebsiteTraffic).filter(
                WebsiteTraffic.competitor_id == cid,
                WebsiteTraffic.snapshot_month == snapshot_month,
            ).first()
            if existing:
                for k, v in row.items():
                    if v is not None:
                        setattr(existing, k, v)
            else:
                s.add(WebsiteTraffic(**row))
            return 1
    except Exception as e:
        log.warning(f"[website_traffic] upsert 失败（{competitor_name}/{snapshot_month}）: {e}")
        return 0


def latest_for_competitor(competitor_name: str) -> dict | None:
    """dashboard 用：取该竞品最新一行。"""
    if not _db.is_mysql_enabled() and not _db.is_sqlite():
        return None
    try:
        with _db.session() as s:
            cid = resolve_competitor_id(competitor_name, sess=s)
            if cid is None:
                return None
            row = (
                s.query(WebsiteTraffic)
                .filter(WebsiteTraffic.competitor_id == cid)
                .order_by(WebsiteTraffic.snapshot_month.desc())
                .first()
            )
            if not row:
                return None
            return {
                "domain": row.domain,
                "snapshot_month": row.snapshot_month.isoformat() if row.snapshot_month else None,
                "monthly_visits": row.monthly_visits,
                "monthly_visits_num": row.monthly_visits_num,
                "avg_visit_duration": row.avg_visit_duration,
                "avg_visit_duration_sec": row.avg_visit_duration_sec,
                "pages_per_visit": row.pages_per_visit,
                "bounce_rate": row.bounce_rate,
                "global_rank": row.global_rank,
                "country_rank": row.country_rank,
                "country_rank_country": row.country_rank_country,
                "category_rank": row.category_rank,
                "male_share": row.male_share,
                "female_share": row.female_share,
                "top_countries": json.loads(row.top_countries_json) if row.top_countries_json else [],
                "similar_sites": json.loads(row.similar_sites_json) if row.similar_sites_json else [],
                "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            }
    except Exception as e:
        log.warning(f"[website_traffic] latest_for_competitor 失败 ({competitor_name}): {e}")
        return None


# ---- helpers --------------------------------------------------------------


def _trim(v, n: int):
    if v is None:
        return None
    s = str(v).strip()
    return s[:n] if s else None


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except Exception:
            return None


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_json(v):
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False)[:8000]
    except Exception:
        return None


# ---- 解析 helpers（爬虫脚本拆字符串用，dao 也暴露便于复用）---------------


_DURATION_RE = re.compile(r"(\d+):(\d+):(\d+)")


def parse_duration(s) -> int | None:
    """'00:05:23' → 323；'5m 23s' → 323；空 → None"""
    if not s:
        return None
    s = str(s).strip()
    m = _DURATION_RE.search(s)
    if m:
        h, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return h * 3600 + mm * 60 + ss
    # "5 min 23 s" / "5m 23s"
    minutes = 0
    seconds = 0
    m2 = re.search(r"(\d+)\s*m", s)
    if m2:
        minutes = int(m2.group(1))
    m3 = re.search(r"(\d+)\s*s", s)
    if m3:
        seconds = int(m3.group(1))
    if minutes or seconds:
        return minutes * 60 + seconds
    return None


def parse_visits(s) -> int | None:
    """'30.5M' → 30500000；'1.2B' → 1200000000；'<5K' / '~10K' → 5000 / 10000"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("~", "").replace("<", "").replace(">", "").strip()
    m = re.match(r"([\d.]+)\s*([KMB]?)", s, re.I)
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    sfx = (m.group(2) or "").upper()
    if sfx == "K":
        n *= 1e3
    elif sfx == "M":
        n *= 1e6
    elif sfx == "B":
        n *= 1e9
    return int(n)


def parse_pct(s) -> float | None:
    """'32.5%' → 0.325；'0.30%' → 0.003；'<1%' → 0.005

    约定：所有传入此函数的字符串都来自页面中带 % 显示的位置，
    即"30.5"代表 30.5% = 0.305，而非 0.305。
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if s.startswith("<"):
        # "<1%" → 取上限的一半作为估值
        try:
            return float(s.lstrip("<").rstrip("%").strip()) / 200.0
        except ValueError:
            return None
    s = s.rstrip("%").strip()
    try:
        n = float(s)
    except ValueError:
        return None
    if n < 0:
        return None
    return n / 100.0
