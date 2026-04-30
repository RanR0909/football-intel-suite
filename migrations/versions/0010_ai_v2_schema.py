"""AI v2 schema: entity_aliases / comment_entities / alerts / failed_ai_jobs + reviews 加 AI 字段

Revision ID: 0010_ai_v2_schema
Revises: 0009_seed_allfootball
Create Date: 2026-04-30 18:00:00.000000

按 AI_tasks_spec_v1_1.md 的 v2 架构要求：
- reviews 加 language / translated_text / labeled_at（comment_label 写入）
- entity_aliases：实体归一表（9 类实体 → canonical_id）
- comment_entities：评论 ↔ 实体的多对多关联
- alerts：7 类预警事件 + AI 生成的 ≤50 字 title
- failed_ai_jobs：AI 任务失败死信队列
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_ai_v2_schema"
down_revision: Union[str, Sequence[str], None] = "0009_seed_allfootball"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- reviews 表加列 ----
    op.add_column("reviews", sa.Column("language", sa.String(length=8)))
    op.add_column("reviews", sa.Column("translated_text", sa.Text()))
    op.add_column("reviews", sa.Column("labeled_at", sa.DateTime()))
    op.create_index("idx_reviews_labeled_at", "reviews", ["labeled_at"])

    # ---- entity_aliases ----
    op.create_table(
        "entity_aliases",
        sa.Column("canonical_id", sa.String(length=64), primary_key=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("primary_name", sa.String(length=255), nullable=False),
        sa.Column("english_name", sa.String(length=255)),
        sa.Column("aliases", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("reviewed_at", sa.DateTime()),
    )
    op.create_index(
        "idx_entity_aliases_type_reviewed", "entity_aliases",
        ["entity_type", "reviewed"],
    )

    # ---- comment_entities ----
    op.create_table(
        "comment_entities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("raw_value", sa.String(length=255)),
        sa.Column("extracted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.ForeignKeyConstraint(["canonical_id"], ["entity_aliases.canonical_id"]),
        sa.UniqueConstraint("review_id", "canonical_id", name="uniq_review_entity"),
    )
    op.create_index("idx_comment_ent_canonical", "comment_entities", ["canonical_id"])
    op.create_index("idx_comment_ent_type", "comment_entities", ["entity_type"])

    # ---- alerts ----
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("alert_type", sa.Enum(
            "ranking", "commercial", "news", "release", "rating", "churn", "ads",
            name="alert_type",
        ), nullable=False),
        sa.Column("severity", sa.Enum(
            "high", "mid", "low", name="alert_severity",
        ), nullable=False, server_default="mid"),
        sa.Column("competitor_id", sa.BigInteger()),
        sa.Column("app_name", sa.String(length=64)),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("title", sa.String(length=120)),
        sa.Column("rule_triggered", sa.String(length=64)),
        sa.Column("fired_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.Enum(
            "new", "ack", "dismissed", name="alert_status",
        ), nullable=False, server_default="new"),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
    )
    op.create_index("idx_alerts_type_fired", "alerts", ["alert_type", "fired_at"])
    op.create_index("idx_alerts_comp_fired", "alerts", ["competitor_id", "fired_at"])
    op.create_index("idx_alerts_status_fired", "alerts", ["status", "fired_at"])

    # ---- failed_ai_jobs ----
    op.create_table(
        "failed_ai_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("task_name", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("error_msg", sa.Text()),
        sa.Column("error_kind", sa.String(length=32)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_failed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime()),
    )
    op.create_index("idx_failed_ai_task_resolved", "failed_ai_jobs", ["task_name", "resolved_at"])


def downgrade() -> None:
    op.drop_index("idx_failed_ai_task_resolved", table_name="failed_ai_jobs")
    op.drop_table("failed_ai_jobs")
    op.drop_index("idx_alerts_status_fired", table_name="alerts")
    op.drop_index("idx_alerts_comp_fired", table_name="alerts")
    op.drop_index("idx_alerts_type_fired", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("idx_comment_ent_type", table_name="comment_entities")
    op.drop_index("idx_comment_ent_canonical", table_name="comment_entities")
    op.drop_table("comment_entities")
    op.drop_index("idx_entity_aliases_type_reviewed", table_name="entity_aliases")
    op.drop_table("entity_aliases")
    op.drop_index("idx_reviews_labeled_at", table_name="reviews")
    op.drop_column("reviews", "labeled_at")
    op.drop_column("reviews", "translated_text")
    op.drop_column("reviews", "language")
