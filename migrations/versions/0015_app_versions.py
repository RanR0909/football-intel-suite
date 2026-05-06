"""create app_versions table (strategy_monitor releaseNotes 持久化)

Revision ID: 0015_app_versions
Revises: 0014_ad_selling_point
Create Date: 2026-05-06 11:15:00.000000

存储每个 app 的版本号 + release notes（iTunes Lookup API 的 releaseNotes 字段）。
spec 里的"产品动态"卡片以版本为单位，每个版本卡显示：
- release notes 中文翻译（comment_label 任务复用）
- 评分变化（vs 上一版本）
- 高频提及实体（comment_entities 关联）

之前 strategy_monitor/changelog_*.py 只把更新写到 JSON，没有持久化版本明细。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_app_versions"
down_revision: Union[str, Sequence[str], None] = "0014_ad_selling_point"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("competitor_id", sa.BigInteger(),
                  sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("platform", sa.Enum("ios", "gp", name="version_platform"), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("release_notes", sa.Text()),                          # 原文（多语言）
        sa.Column("release_notes_lang", sa.String(length=8)),           # 检测到的原文语言
        sa.Column("release_notes_translated_zh", sa.Text()),            # comment_label 翻译后中文
        sa.Column("translated_at", sa.DateTime()),                      # 翻译完成时间，NULL = 未翻
        sa.Column("released_at", sa.DateTime()),                        # iTunes currentVersionReleaseDate
        sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("competitor_id", "platform", "version", name="uniq_app_version"),
    )
    op.create_index("idx_app_versions_released_at", "app_versions", ["released_at"])
    op.create_index("idx_app_versions_comp_released", "app_versions",
                    ["competitor_id", "released_at"])


def downgrade() -> None:
    op.drop_index("idx_app_versions_comp_released", table_name="app_versions")
    op.drop_index("idx_app_versions_released_at", table_name="app_versions")
    op.drop_table("app_versions")
