"""SQLAlchemy ORM models — 8 张表（2 lookup + 6 fact）。

设计原则：
- 抓取脚本只写 fact 表；lookup 表通过 Alembic 0001_init seed
- competitor_id 在 fact 表里允许 NULL（非 tracked 应用 / lookup 失败兜底）
- 所有 fact 表带 fetched_at；time-series 表（market_rank_snapshots / sync_log）带额外日期字段
- 索引按主要查询路径（[competitor, region, time]）

字段尽量保留原始字符串（如 IAP price `$9.99`），同时 parse 后存数值（price_num）便于 SQL 聚合。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Date, DECIMAL, Enum,
    Float, ForeignKey, Integer, Index, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# SQLite 不会对 BigInteger 自增；测试用 SQLite 时 PK 走 Integer。MySQL 仍 BigInteger。
PK_BigInt = BigInteger().with_variant(Integer, "sqlite")


# ---- Lookup 表 -----------------------------------------------------------

class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    gp_package = Column(String(128))
    ios_app_id = Column(String(32))
    bundle_id = Column(String(128))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Region(Base):
    __tablename__ = "regions"

    code = Column(String(8), primary_key=True)
    label = Column(String(32), nullable=False)
    lang = Column(String(8), nullable=False)


# ---- Fact 表 -------------------------------------------------------------

class Review(Base):
    __tablename__ = "reviews"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    competitor_id = Column(BigInteger, ForeignKey("competitors.id"), nullable=False)
    region_code = Column(String(8), nullable=False)
    platform = Column(Enum("gp", "ios", name="review_platform"), nullable=False)
    score = Column(SmallInteger)
    version = Column(String(32))
    content = Column(Text)
    label = Column(String(32))
    at = Column(DateTime)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_reviews_comp_region_at", "competitor_id", "region_code", "at"),
        Index("idx_reviews_label", "label"),
    )


class AdCreative(Base):
    __tablename__ = "ad_creatives"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    competitor_id = Column(BigInteger, ForeignKey("competitors.id"), nullable=False)
    region_code = Column(String(8), nullable=False)
    ad_id = Column(String(64), nullable=False)
    text = Column(Text)
    start_date = Column(String(64))
    platform = Column(String(64))
    page_name = Column(String(128))
    media_url = Column(String(1024))
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("competitor_id", "ad_id", name="uniq_ad_creative"),
        Index("idx_ad_comp_fetched", "competitor_id", "fetched_at"),
    )


class IapItem(Base):
    __tablename__ = "iap_items"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    competitor_id = Column(BigInteger, ForeignKey("competitors.id"), nullable=False)
    region_code = Column(String(8), nullable=False)
    name = Column(String(255), nullable=False)
    price = Column(String(32))            # 原始字符串
    price_num = Column(DECIMAL(10, 2))    # 解析数值
    currency = Column(String(8))
    category = Column(String(32))
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_iap_comp_region_fetched", "competitor_id", "region_code", "fetched_at"),
    )


class MarketRankSnapshot(Base):
    __tablename__ = "market_rank_snapshots"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    source = Column(Enum("appmagic", "appstore_rank", "sensor_tower", "androidrank",
                         name="rank_source"),
                    nullable=False)
    region_code = Column(String(8))   # NULL = worldwide
    competitor_id = Column(BigInteger, ForeignKey("competitors.id"))  # NULL = 非 tracked
    name = Column(String(128))
    rank_value = Column(Integer)
    delta = Column(Integer)
    downloads = Column(String(32))             # 原始字符串 ("~10K" / "200K") 或解析后数值的字符串
    downloads_num = Column(BigInteger)         # 解析后整数（便于 SQL 聚合）— sensor_tower 给 200000 这种
    revenue_num = Column(BigInteger)           # 月收入估算（sensor_tower 专供，单位 USD）
    snapshot_date = Column(Date, nullable=False)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_rank_source_region_date", "source", "region_code", "snapshot_date"),
        Index("idx_rank_comp_date", "competitor_id", "snapshot_date"),
    )


class CommunityPost(Base):
    __tablename__ = "community_posts"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    competitor_id = Column(BigInteger, ForeignKey("competitors.id"), nullable=False)
    source = Column(Enum("reddit", "twitter", name="community_source"), nullable=False)
    post_id = Column(String(64), nullable=False)
    subreddit = Column(String(64))
    title = Column(String(512))
    selftext = Column(Text)
    score = Column(Integer)
    num_comments = Column(Integer)
    url = Column(String(1024))
    created_utc = Column(DateTime)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source", "post_id", name="uniq_post"),
        Index("idx_post_comp_created", "competitor_id", "created_utc"),
    )


class WebsiteTraffic(Base):
    """Similarweb 公开页快照（每周一次，monthly_visits 等数据 Similarweb 月级更新）。

    一行 = (competitor, snapshot_month) 的官网流量整体画像。设计：
    - 6 个流量来源百分比（direct/search/social/referral/mail/display）单独列
    - 设备占比（desktop/mobile）单独列
    - 数值 + 原始字符串双写："30.5M" → 30500000；"00:05:23" → 323
    - 长尾详情（top countries / keywords）存 JSON
    """
    __tablename__ = "website_traffic"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    competitor_id = Column(BigInteger, ForeignKey("competitors.id"), nullable=False)
    domain = Column(String(128), nullable=False)
    snapshot_month = Column(Date, nullable=False)   # 数据所属月份（每月 1 号）

    # 核心 4 指标
    monthly_visits = Column(String(32))             # "30.5M"
    monthly_visits_num = Column(BigInteger)         # 30500000
    avg_visit_duration = Column(String(16))         # "00:05:23"
    avg_visit_duration_sec = Column(Integer)        # 323
    pages_per_visit = Column(Float)                 # 5.43
    bounce_rate = Column(Float)                     # 0.325（小数 0–1）

    # 排名（anonymous 也有，长期稳定）
    global_rank = Column(Integer)
    country_rank = Column(Integer)
    country_rank_country = Column(String(64))       # e.g. "Brazil"
    category_rank = Column(Integer)

    # 性别画像（anonymous 显示，trial 不显示在概览页）
    male_share = Column(Float)
    female_share = Column(Float)

    # 长尾详情（非索引）
    top_countries_json = Column(Text)               # [{country, share}, ...]
    similar_sites_json = Column(Text)               # [{domain, affinity}, ...]
    raw_text = Column(Text)                         # main innerText 前 4000 字（调试）

    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("competitor_id", "snapshot_month", name="uniq_traffic_comp_month"),
        Index("idx_traffic_comp_month", "competitor_id", "snapshot_month"),
    )


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    script = Column(String(64), nullable=False)
    label = Column(String(64))
    competitor = Column(String(64))
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)
    duration_sec = Column(Float)
    success = Column(Boolean, nullable=False)
    error_kind = Column(String(32))
    stdout_tail = Column(Text)
    stderr_tail = Column(Text)
    cmd = Column(String(512))

    __table_args__ = (
        Index("idx_synclog_script_started", "script", "started_at"),
    )


# 表名清单（dashboard 健康检查用）
ALL_TABLES = [
    "competitors", "regions",
    "reviews", "ad_creatives", "iap_items",
    "market_rank_snapshots", "community_posts",
    "website_traffic", "sync_log",
]
