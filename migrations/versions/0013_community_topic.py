"""community_posts 加 topic_classified 等 AI 字段 (task #6 post_topic_classifier)

Revision ID: 0013_community_topic
Revises: 0012_news_items
Create Date: 2026-05-06 11:05:00.000000

任务 6 (post_topic_classifier) 给每条 reddit/twitter 帖子打 8 类主题 +
0-2 个次主题 + 命中竞品。前端按 primary_topic 聚合展示。

铁律 4: 已分类 (topic_classified_at IS NOT NULL) 的帖子不重复跑。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_community_topic"
down_revision: Union[str, Sequence[str], None] = "0012_news_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 8 类主题 — 用 String(32) 而非 Enum，方便后续扩展
    op.add_column("community_posts", sa.Column("primary_topic", sa.String(length=32)))
    op.add_column("community_posts", sa.Column("secondary_topics", sa.Text()))      # JSON ["competitor_compare"]
    op.add_column("community_posts", sa.Column("competitor_mentioned", sa.String(length=64)))
    op.add_column("community_posts", sa.Column("topic_classified_at", sa.DateTime()))
    op.add_column("community_posts", sa.Column("topic_confidence", sa.Numeric(3, 2)))
    op.create_index("idx_post_primary_topic", "community_posts", ["primary_topic"])
    op.create_index("idx_post_competitor_mention", "community_posts", ["competitor_mentioned"])
    op.create_index("idx_post_topic_classified_at", "community_posts", ["topic_classified_at"])


def downgrade() -> None:
    op.drop_index("idx_post_topic_classified_at", table_name="community_posts")
    op.drop_index("idx_post_competitor_mention", table_name="community_posts")
    op.drop_index("idx_post_primary_topic", table_name="community_posts")
    op.drop_column("community_posts", "topic_confidence")
    op.drop_column("community_posts", "topic_classified_at")
    op.drop_column("community_posts", "competitor_mentioned")
    op.drop_column("community_posts", "secondary_topics")
    op.drop_column("community_posts", "primary_topic")
