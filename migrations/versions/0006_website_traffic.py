"""create website_traffic table (similarweb)

Revision ID: 0006_website_traffic
Revises: 543643e209f9
Create Date: 2026-04-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_website_traffic"
down_revision: Union[str, Sequence[str], None] = "543643e209f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "website_traffic",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("competitor_id", sa.BigInteger(), nullable=False),
        sa.Column("domain", sa.String(length=128), nullable=False),
        sa.Column("snapshot_month", sa.Date(), nullable=False),

        # 核心 4 指标
        sa.Column("monthly_visits", sa.String(length=32)),
        sa.Column("monthly_visits_num", sa.BigInteger()),
        sa.Column("avg_visit_duration", sa.String(length=16)),
        sa.Column("avg_visit_duration_sec", sa.Integer()),
        sa.Column("pages_per_visit", sa.Float()),
        sa.Column("bounce_rate", sa.Float()),

        # 设备
        sa.Column("desktop_share", sa.Float()),
        sa.Column("mobile_share", sa.Float()),

        # 6 个流量来源
        sa.Column("direct_share", sa.Float()),
        sa.Column("search_share", sa.Float()),
        sa.Column("social_share", sa.Float()),
        sa.Column("referral_share", sa.Float()),
        sa.Column("mail_share", sa.Float()),
        sa.Column("display_share", sa.Float()),

        # 长尾详情
        sa.Column("top_countries_json", sa.Text()),
        sa.Column("top_keywords_json", sa.Text()),
        sa.Column("raw_text", sa.Text()),

        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),

        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
        sa.UniqueConstraint("competitor_id", "snapshot_month", name="uniq_traffic_comp_month"),
    )
    op.create_index(
        "idx_traffic_comp_month", "website_traffic",
        ["competitor_id", "snapshot_month"],
    )


def downgrade() -> None:
    op.drop_index("idx_traffic_comp_month", table_name="website_traffic")
    op.drop_table("website_traffic")
