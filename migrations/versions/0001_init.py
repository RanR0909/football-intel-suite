"""init: 8 tables + seed lookup data

Revision ID: 0001
Revises:
Create Date: 2026-04-28
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def upgrade() -> None:
    # ---- competitors ----
    op.create_table(
        "competitors",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("gp_package", sa.String(128)),
        sa.Column("ios_app_id", sa.String(32)),
        sa.Column("bundle_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        mysql_charset="utf8mb4",
    )

    # ---- regions ----
    op.create_table(
        "regions",
        sa.Column("code", sa.String(8), primary_key=True),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("lang", sa.String(8), nullable=False),
        mysql_charset="utf8mb4",
    )

    # ---- reviews ----
    op.create_table(
        "reviews",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("competitor_id", sa.BigInteger, sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("region_code", sa.String(8), nullable=False),
        sa.Column("platform", sa.Enum("gp", "ios", name="review_platform"), nullable=False),
        sa.Column("score", sa.SmallInteger),
        sa.Column("version", sa.String(32)),
        sa.Column("content", sa.Text),
        sa.Column("label", sa.String(32)),
        sa.Column("at", sa.DateTime),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_reviews_comp_region_at", "reviews", ["competitor_id", "region_code", "at"])
    op.create_index("idx_reviews_label", "reviews", ["label"])

    # ---- ad_creatives ----
    op.create_table(
        "ad_creatives",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("competitor_id", sa.BigInteger, sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("region_code", sa.String(8), nullable=False),
        sa.Column("ad_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("start_date", sa.String(64)),
        sa.Column("platform", sa.String(64)),
        sa.Column("page_name", sa.String(128)),
        sa.Column("media_url", sa.String(1024)),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("competitor_id", "ad_id", name="uniq_ad_creative"),
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_ad_comp_fetched", "ad_creatives", ["competitor_id", "fetched_at"])

    # ---- iap_items ----
    op.create_table(
        "iap_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("competitor_id", sa.BigInteger, sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("region_code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("price", sa.String(32)),
        sa.Column("price_num", sa.DECIMAL(10, 2)),
        sa.Column("currency", sa.String(8)),
        sa.Column("category", sa.String(32)),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_iap_comp_region_fetched", "iap_items",
                    ["competitor_id", "region_code", "fetched_at"])

    # ---- market_rank_snapshots ----
    op.create_table(
        "market_rank_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Enum("appmagic", "appstore_rank", "sensor_tower",
                                    name="rank_source"), nullable=False),
        sa.Column("region_code", sa.String(8)),
        sa.Column("competitor_id", sa.BigInteger, sa.ForeignKey("competitors.id")),
        sa.Column("name", sa.String(128)),
        sa.Column("rank_value", sa.Integer),
        sa.Column("delta", sa.Integer),
        sa.Column("downloads", sa.String(32)),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_rank_source_region_date", "market_rank_snapshots",
                    ["source", "region_code", "snapshot_date"])
    op.create_index("idx_rank_comp_date", "market_rank_snapshots",
                    ["competitor_id", "snapshot_date"])

    # ---- community_posts ----
    op.create_table(
        "community_posts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("competitor_id", sa.BigInteger, sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("source", sa.Enum("reddit", "twitter", name="community_source"), nullable=False),
        sa.Column("post_id", sa.String(64), nullable=False),
        sa.Column("subreddit", sa.String(64)),
        sa.Column("title", sa.String(512)),
        sa.Column("selftext", sa.Text),
        sa.Column("score", sa.Integer),
        sa.Column("num_comments", sa.Integer),
        sa.Column("url", sa.String(1024)),
        sa.Column("created_utc", sa.DateTime),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("source", "post_id", name="uniq_post"),
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_post_comp_created", "community_posts",
                    ["competitor_id", "created_utc"])

    # ---- sync_log ----
    op.create_table(
        "sync_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("script", sa.String(64), nullable=False),
        sa.Column("label", sa.String(64)),
        sa.Column("competitor", sa.String(64)),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("duration_sec", sa.Float),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error_kind", sa.String(32)),
        sa.Column("stdout_tail", sa.Text),
        sa.Column("stderr_tail", sa.Text),
        sa.Column("cmd", sa.String(512)),
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_synclog_script_started", "sync_log", ["script", "started_at"])

    # ---- seed lookup data ----
    _seed_lookups()


def downgrade() -> None:
    op.drop_index("idx_synclog_script_started", table_name="sync_log")
    op.drop_table("sync_log")
    op.drop_index("idx_post_comp_created", table_name="community_posts")
    op.drop_table("community_posts")
    op.drop_index("idx_rank_comp_date", table_name="market_rank_snapshots")
    op.drop_index("idx_rank_source_region_date", table_name="market_rank_snapshots")
    op.drop_table("market_rank_snapshots")
    op.drop_index("idx_iap_comp_region_fetched", table_name="iap_items")
    op.drop_table("iap_items")
    op.drop_index("idx_ad_comp_fetched", table_name="ad_creatives")
    op.drop_table("ad_creatives")
    op.drop_index("idx_reviews_label", table_name="reviews")
    op.drop_index("idx_reviews_comp_region_at", table_name="reviews")
    op.drop_table("reviews")
    op.drop_table("regions")
    op.drop_table("competitors")


def _seed_lookups() -> None:
    """从 data/competitors.json + data/regions.json 灌入 lookup 表。"""
    root = _project_root()
    competitors_json = root / "data" / "competitors.json"
    regions_json = root / "data" / "regions.json"

    bind = op.get_bind()

    # competitors（不带 created_at，数据库自动填）
    if competitors_json.exists():
        comp_data = json.loads(competitors_json.read_text(encoding="utf-8"))
        rows = []
        for name, info in comp_data.items():
            rows.append({
                "name": name,
                "gp_package": info.get("gp"),
                "ios_app_id": str(info.get("ios") or info.get("app_id") or ""),
                "bundle_id": info.get("bundle_id"),
            })
        if rows:
            t = sa.Table("competitors", sa.MetaData(),
                         sa.Column("name", sa.String(64)),
                         sa.Column("gp_package", sa.String(128)),
                         sa.Column("ios_app_id", sa.String(32)),
                         sa.Column("bundle_id", sa.String(128)))
            bind.execute(t.insert(), rows)

    # regions
    if regions_json.exists():
        reg_data = json.loads(regions_json.read_text(encoding="utf-8"))
        rows = [{"code": code, "label": v.get("label", code), "lang": v.get("lang", "en")}
                for code, v in reg_data.items()]
        if rows:
            t = sa.Table("regions", sa.MetaData(),
                         sa.Column("code", sa.String(8)),
                         sa.Column("label", sa.String(32)),
                         sa.Column("lang", sa.String(8)))
            bind.execute(t.insert(), rows)
