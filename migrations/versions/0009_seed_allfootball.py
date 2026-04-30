"""seed AllFootball into competitors lookup (data analysis baseline)

Revision ID: 0009_seed_allfootball
Revises: 0008_drop_trial_only
Create Date: 2026-04-30 17:00:00.000000

AllFootball（自家产品 / 数据分析 baseline）需要 lookup 表里有对应行，
否则 DAO 写各 fact 表（reviews / community_posts / iap_items / ...）时
resolve_competitor_id 找不到映射会被跳过。

非破坏性 — 仅 INSERT 一行。重跑（downgrade）会 DELETE。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_seed_allfootball"
down_revision: Union[str, Sequence[str], None] = "0008_drop_trial_only"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_AF_ROW = {
    "name": "AllFootball",
    "gp_package": "com.allfootball.news",
    "ios_app_id": "1171012600",
    "bundle_id": "com.allfootballapp.news",
}


def upgrade() -> None:
    bind = op.get_bind()
    # 先查是否已存在（手动跑过 INSERT 的情况下幂等）
    existing = bind.execute(
        sa.text("SELECT 1 FROM competitors WHERE name = :n"), {"n": _AF_ROW["name"]}
    ).first()
    if existing:
        return
    t = sa.Table(
        "competitors", sa.MetaData(),
        sa.Column("name", sa.String(64)),
        sa.Column("gp_package", sa.String(128)),
        sa.Column("ios_app_id", sa.String(32)),
        sa.Column("bundle_id", sa.String(128)),
    )
    bind.execute(t.insert().values(**_AF_ROW))


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM competitors WHERE name = :n").bindparams(n=_AF_ROW["name"])
    )
