"""create community_post_entities table

Revision ID: 0016_community_post_entities
Revises: 0015_app_versions
Create Date: 2026-05-06 12:00:00.000000

社媒帖子 ↔ 实体多对多关联（schema 与 comment_entities 完全相同，
只是外键从 review_id 改为 post_id 指向 community_posts.id）。

写入方：ai_tasks/post_entity_extract.py 跑 entity_extract on community_posts
读取方：dashboard_server.api_community_aggregated?dim=player|league
        — JOIN entity_aliases 按 entity_type 聚合
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_community_post_entities"
down_revision: Union[str, Sequence[str], None] = "0015_app_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "community_post_entities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("raw_value", sa.String(length=255)),
        sa.Column("extracted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["post_id"], ["community_posts.id"]),
        sa.ForeignKeyConstraint(["canonical_id"], ["entity_aliases.canonical_id"]),
        sa.UniqueConstraint("post_id", "canonical_id", name="uniq_post_entity"),
    )
    op.create_index("idx_post_ent_canonical", "community_post_entities", ["canonical_id"])
    op.create_index("idx_post_ent_type", "community_post_entities", ["entity_type"])
    # community_posts 加 entity_extracted_at 标志位，跟 reviews.labeled_at 模式一致
    op.add_column("community_posts", sa.Column("entity_extracted_at", sa.DateTime()))
    op.create_index("idx_post_entity_extracted_at", "community_posts", ["entity_extracted_at"])


def downgrade() -> None:
    op.drop_index("idx_post_entity_extracted_at", table_name="community_posts")
    op.drop_column("community_posts", "entity_extracted_at")
    op.drop_index("idx_post_ent_type", table_name="community_post_entities")
    op.drop_index("idx_post_ent_canonical", table_name="community_post_entities")
    op.drop_table("community_post_entities")
