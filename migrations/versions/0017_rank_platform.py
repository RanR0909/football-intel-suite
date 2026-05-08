"""add platform column to market_rank_snapshots

Revision ID: 0017_rank_platform
Revises: 0016_community_post_entities
Create Date: 2026-05-08 11:30:00.000000

之前 sensor_tower 只跑 iOS（SCRAPE_PLATFORM='ios' 硬编码），无法区分平台。
现在 scraper 拆 ios + android 两个 task，需要在 fact 表里区分。

历史数据回填：
  · sensor_tower 全部行 platform='ios'（之前唯一抓的）
  · androidrank 全部行 platform='android'（源本身就是 Android-only）
  · appmagic / appstore_rank 留 NULL（这两个源是榜单类，本身就单平台默认 iOS，不细分）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_rank_platform"
down_revision: Union[str, Sequence[str], None] = "0016_community_post_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "market_rank_snapshots",
        sa.Column("platform", sa.String(8), nullable=True),
    )
    # 历史数据回填
    op.execute(
        "UPDATE market_rank_snapshots SET platform='ios' "
        "WHERE source='sensor_tower' AND platform IS NULL"
    )
    op.execute(
        "UPDATE market_rank_snapshots SET platform='android' "
        "WHERE source='androidrank' AND platform IS NULL"
    )
    # 复合索引：按 (source, platform, snapshot_date) 查最新数据
    op.create_index(
        "idx_rank_source_platform_date",
        "market_rank_snapshots",
        ["source", "platform", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_rank_source_platform_date", table_name="market_rank_snapshots")
    op.drop_column("market_rank_snapshots", "platform")
