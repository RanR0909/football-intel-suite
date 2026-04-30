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
    # AI v2 字段（comment_label 任务写入）
    label = Column(String(32))                     # 6 类之一：complaint/feature_request/competitor_compare/churn_signal/positive/other
    language = Column(String(8))                   # 检测到的原语言（en/es/pt/ar/ja/zh ...）
    translated_text = Column(Text)                 # 中文翻译（comment_label 任务输出）
    labeled_at = Column(DateTime)                  # AI 处理完成时间
    at = Column(DateTime)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_reviews_comp_region_at", "competitor_id", "region_code", "at"),
        Index("idx_reviews_label", "label"),
        Index("idx_reviews_labeled_at", "labeled_at"),
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


# ─────────────────────────── AI v2 表 (2026-04-30) ───────────────────────────


class EntityAlias(Base):
    """实体归一表（AI v2 / entity_extract 任务）。

    每个 canonical_id 是一个去重后的实体（球员 / 球队 / 联赛 / 功能 / bug ...），
    aliases 字段存所有已知别名（用于 entity_extract 时优先查表，命中即跳过 AI）。
    新别名 / 新 canonical 由 AI 创建 + 标 reviewed=False，等周批人工审核。
    """
    __tablename__ = "entity_aliases"

    canonical_id = Column(String(64), primary_key=True)
    entity_type = Column(String(32), nullable=False)            # 9 类：competitor / feature / league / player / device / bug / localization / payment / language
    primary_name = Column(String(255), nullable=False)          # 主名（中文优先）
    english_name = Column(String(255))                          # 英文名（可选，便于交叉查找）
    aliases = Column(Text)                                       # JSON list（[" 别名 1", "alias 2", ...]）— 用 Text 而非 JSON 以兼容 SQLite
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed = Column(Boolean, nullable=False, default=False)
    reviewed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_entity_aliases_type_reviewed", "entity_type", "reviewed"),
    )


class CommentEntity(Base):
    """评论 ↔ 实体 关联表（多对多，AI v2 / entity_extract 任务输出）。"""
    __tablename__ = "comment_entities"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    review_id = Column(BigInteger, ForeignKey("reviews.id"), nullable=False)
    canonical_id = Column(String(64), ForeignKey("entity_aliases.canonical_id"), nullable=False)
    entity_type = Column(String(32), nullable=False)            # 冗余存一份便于按类型查
    raw_value = Column(String(255))                              # 评论中出现的原始字面量
    extracted_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("review_id", "canonical_id", name="uniq_review_entity"),
        Index("idx_comment_ent_canonical", "canonical_id"),
        Index("idx_comment_ent_type", "entity_type"),
    )


class Alert(Base):
    """告警事件表（alert_engine 规则匹配 + AI 写 title）。

    alert_engine 每日 02:30 跑一次：扫各 fact 表找符合 7 类规则的事件，
    每条事件写一行到本表，调用 alert_title 任务生成 title 字段。
    """
    __tablename__ = "alerts"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    alert_type = Column(Enum(
        "ranking", "commercial", "news", "release", "rating", "churn", "ads",
        name="alert_type",
    ), nullable=False)
    severity = Column(Enum("high", "mid", "low", name="alert_severity"),
                      nullable=False, default="mid")
    competitor_id = Column(BigInteger, ForeignKey("competitors.id"))   # NULL = 跨多竞品 / 行业事件
    app_name = Column(String(64))                                       # 冗余便于直接看
    metadata_json = Column(Text)                                        # JSON dict — 7 类各有自己的 schema
    title = Column(String(120))                                         # AI 生成的 ≤50 字事实陈述（容错给 120）
    rule_triggered = Column(String(64))                                 # 触发规则名（便于审计）
    fired_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(Enum("new", "ack", "dismissed", name="alert_status"),
                    nullable=False, default="new")

    __table_args__ = (
        Index("idx_alerts_type_fired", "alert_type", "fired_at"),
        Index("idx_alerts_comp_fired", "competitor_id", "fired_at"),
        Index("idx_alerts_status_fired", "status", "fired_at"),
    )


class FailedAiJob(Base):
    """失败 AI 任务的死信队列。run_task 重试耗尽后写入这里，等人工或定时重跑。"""
    __tablename__ = "failed_ai_jobs"

    id = Column(PK_BigInt, primary_key=True, autoincrement=True)
    task_name = Column(String(64), nullable=False)              # comment_label / entity_extract / alert_title
    payload_json = Column(Text, nullable=False)                  # 调用 run_task 的 context 序列化（用于重放）
    error_msg = Column(Text)
    error_kind = Column(String(32))                              # http / json_parse / timeout / unknown
    attempts = Column(Integer, nullable=False, default=1)
    first_failed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_attempt_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime)                               # 重试成功后填，便于 SELECT WHERE resolved_at IS NULL

    __table_args__ = (
        Index("idx_failed_ai_task_resolved", "task_name", "resolved_at"),
    )


# ─────────────────────────── 已有表 ───────────────────────────


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
    "website_traffic",
    # AI v2
    "entity_aliases", "comment_entities", "alerts", "failed_ai_jobs",
    "sync_log",
]
