"""add chinese_name + translated_at columns to entity_aliases

Revision ID: 0018_entity_chinese_name
Revises: 0017_rank_platform
Create Date: 2026-05-08 11:45:00.000000

GP Reviews 聚合页（problems / praise / localization / churn 4 个 tab）展示的是
entity_aliases.primary_name —— 实际是 entity_extract AI 抽出的原文，多语言混杂
（英语 / 葡语 / 西语 / 阿语 / 中文都有），用户阅读不便。

新加 chinese_name 列：通过 ai_tasks/translate_entity_names.py 批量翻译为简洁
中文（≤10字名词性短语），前端 fallback 链：chinese_name → primary_name。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_entity_chinese_name"
down_revision: Union[str, Sequence[str], None] = "0017_rank_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_aliases",
        sa.Column("chinese_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "entity_aliases",
        sa.Column("translated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_aliases", "translated_at")
    op.drop_column("entity_aliases", "chinese_name")
