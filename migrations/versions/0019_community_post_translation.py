"""add title_zh + selftext_zh + translated_at to community_posts

Revision ID: 0019_community_post_translation
Revises: 0018_entity_chinese_name
Create Date: 2026-05-08 14:30:00.000000

社媒帖子（Reddit + Twitter）原文绝大多数是英语，社媒评论页面的"产品信号" tab
直接展示原帖标题和正文，对中文用户阅读不便。

新加 title_zh / selftext_zh：通过 ai_tasks/translate_community_posts.py 批量
翻译为中文，前端 fallback chinese → original。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_community_post_translation"
down_revision: Union[str, Sequence[str], None] = "0018_entity_chinese_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "community_posts",
        sa.Column("title_zh", sa.String(512), nullable=True),
    )
    op.add_column(
        "community_posts",
        sa.Column("selftext_zh", sa.Text, nullable=True),
    )
    op.add_column(
        "community_posts",
        sa.Column("translated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("community_posts", "translated_at")
    op.drop_column("community_posts", "selftext_zh")
    op.drop_column("community_posts", "title_zh")
