"""create news_items table (Google News RSS + AI v2 task #5: news_classifier)

Revision ID: 0012_news_items
Revises: 0011_app_classifications
Create Date: 2026-05-06 11:00:00.000000

Google News RSS 抓回的原始新闻条目入库（之前只输出到 data/async_google_news.json）。
表 schema 同时容纳 task #5 (news_classifier) 的 AI 分类输出，避免下个 migration 再 ALTER。

字段分两段：
- 抓取层（async_crawler/sources/google_news.py 写入）
    title / snippet / source / url / published_at / matched_keyword / app_name
- AI 层（ai_tasks/news_classifier.py 写入）
    is_business / business_category / competitors_mentioned /
    classified_at / classification_confidence

铁律 4 落地：news_classifier 只处理 classified_at IS NULL 的行。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_news_items"
down_revision: Union[str, Sequence[str], None] = "0011_app_classifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        # ---- 抓取层 ----
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("snippet", sa.Text()),                              # spec 字段：摘要 (google_news 里的 desc)
        sa.Column("source", sa.String(length=128)),                   # techcrunch.com 等域名
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("published_at", sa.DateTime()),                     # google news pubDate 解析后
        sa.Column("matched_keyword", sa.String(length=128)),          # 触发命中的关键词
        sa.Column("app_name", sa.String(length=64)),                  # 抓取时关联的 9 竞品 + AF
        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        # ---- AI 层（task #5 news_classifier 写入）----
        sa.Column("is_business", sa.Boolean()),                       # NULL = 未分类；True/False = AI 判定结果
        sa.Column("business_category", sa.String(length=32)),         # funding/acquisition/partnership/launch/strategy/hiring/legal/other
        sa.Column("competitors_mentioned", sa.Text()),                # JSON array: ["SofaScore", "FotMob"]
        sa.Column("classification_confidence", sa.Numeric(3, 2)),     # 0.00 - 1.00
        sa.Column("classified_at", sa.DateTime()),                    # NULL = 未分类（重复跑判定）
        sa.UniqueConstraint("url", name="uniq_news_url"),
    )
    op.create_index("idx_news_published", "news_items", ["published_at"])
    op.create_index("idx_news_classified_at", "news_items", ["classified_at"])
    op.create_index("idx_news_business", "news_items", ["is_business", "business_category"])
    op.create_index("idx_news_app", "news_items", ["app_name", "published_at"])


def downgrade() -> None:
    op.drop_index("idx_news_app", table_name="news_items")
    op.drop_index("idx_news_business", table_name="news_items")
    op.drop_index("idx_news_classified_at", table_name="news_items")
    op.drop_index("idx_news_published", table_name="news_items")
    op.drop_table("news_items")
