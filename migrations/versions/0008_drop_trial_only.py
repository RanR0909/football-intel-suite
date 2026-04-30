"""drop trial-only columns from website_traffic

Revision ID: 0008_drop_trial_only
Revises: 0007_website_traffic_extra
Create Date: 2026-04-30 16:30:00.000000

Similarweb 的 device split / 6 大流量来源 / top_keywords 仅在 Premium Trial
（新账号 8 天）期间可见，trial 过期后会变 null。为避免出现长期 null 列影响
dashboard 与查询，将这些字段从 schema 中移除。

未来若需要恢复（例如统一改用 anonymous 模式 / 续 Premium 账号），可参考此
migration 反向操作。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_drop_trial_only"
down_revision: Union[str, Sequence[str], None] = "0007_website_traffic_extra"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DROPPED_COLS = [
    "desktop_share",
    "mobile_share",
    "direct_share",
    "search_share",
    "social_share",
    "referral_share",
    "mail_share",
    "display_share",
    "top_keywords_json",
]


def upgrade() -> None:
    for col in _DROPPED_COLS:
        op.drop_column("website_traffic", col)


def downgrade() -> None:
    op.add_column("website_traffic", sa.Column("top_keywords_json", sa.Text()))
    op.add_column("website_traffic", sa.Column("display_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("mail_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("referral_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("social_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("search_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("direct_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("mobile_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("desktop_share", sa.Float()))
