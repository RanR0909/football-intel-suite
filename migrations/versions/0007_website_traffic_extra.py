"""extend website_traffic with rank / demographics / similar_sites fields

Revision ID: 0007_website_traffic_extra
Revises: 0006_website_traffic
Create Date: 2026-04-30 16:00:00.000000

新增字段都是 anonymous（不登录）也能看的稳定字段，trial 过期后还在：
- global_rank / country_rank / country_rank_country / category_rank
- male_share / female_share
- similar_sites_json
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_website_traffic_extra"
down_revision: Union[str, Sequence[str], None] = "0006_website_traffic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("website_traffic", sa.Column("global_rank", sa.Integer()))
    op.add_column("website_traffic", sa.Column("country_rank", sa.Integer()))
    op.add_column("website_traffic", sa.Column("country_rank_country", sa.String(length=64)))
    op.add_column("website_traffic", sa.Column("category_rank", sa.Integer()))
    op.add_column("website_traffic", sa.Column("male_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("female_share", sa.Float()))
    op.add_column("website_traffic", sa.Column("similar_sites_json", sa.Text()))


def downgrade() -> None:
    op.drop_column("website_traffic", "similar_sites_json")
    op.drop_column("website_traffic", "female_share")
    op.drop_column("website_traffic", "male_share")
    op.drop_column("website_traffic", "category_rank")
    op.drop_column("website_traffic", "country_rank_country")
    op.drop_column("website_traffic", "country_rank")
    op.drop_column("website_traffic", "global_rank")
