"""create app_classifications table (AI v2 task #4: app_classifier)

Revision ID: 0011_app_classifications
Revises: 0010_ai_v2_schema
Create Date: 2026-04-30 19:00:00.000000

第 4 个 AI 任务：从 App Store / GP 拿一个 app 的 metadata，
让 Claude Haiku 4.5 输出结构化分类（is_relevant / topic / categories / confidence）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_app_classifications"
down_revision: Union[str, Sequence[str], None] = "0010_ai_v2_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_classifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("app_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.Enum("gp", "ios", name="app_class_platform"), nullable=False),
        sa.Column("bundle_id", sa.String(length=128)),
        sa.Column("name", sa.String(length=255)),
        sa.Column("publisher", sa.String(length=255)),
        sa.Column("category", sa.String(length=64)),
        sa.Column("description_excerpt", sa.Text()),
        sa.Column("matched_keywords", sa.Text()),
        sa.Column("is_relevant", sa.Boolean()),
        sa.Column("topic", sa.String(length=16)),
        sa.Column("categories", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("rejection_reason", sa.String(length=255)),
        sa.Column("classified_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("app_id", "platform", name="uniq_app_class"),
    )
    op.create_index("idx_app_class_topic_relevant", "app_classifications", ["topic", "is_relevant"])
    op.create_index("idx_app_class_classified_at", "app_classifications", ["classified_at"])


def downgrade() -> None:
    op.drop_index("idx_app_class_classified_at", table_name="app_classifications")
    op.drop_index("idx_app_class_topic_relevant", table_name="app_classifications")
    op.drop_table("app_classifications")
