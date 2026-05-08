"""add version_type / key_changes_json / is_significant / classified_at to app_versions

Revision ID: 0020_app_version_classify
Revises: 0019_community_post_translation
Create Date: 2026-05-08 15:00:00.000000

产品动态页（/content/releases）只能展示 release_notes 原文，10 个版本平铺无差异 —
"AllFootball: bug fixes" 跟 "Fotmob: Lineup Builder 上线" 视觉地位一样，用户难以
快速识别哪些更新值得关注。

新加 4 列由 ai_tasks/classify_app_versions.py 写入：
- version_type: feature | bugfix | localization | performance | other
- key_changes_json: JSON array, 1-3 个中文短句（≤20 字），卡头展示用
- is_significant: 重要更新（feature/major changes）vs 普通（pure bugfix）
- classified_at: 写入时间，NULL = 还没分类

(release_notes_translated_zh + translated_at 字段早就在 0015 migration 里了，
 只是从来没填过 — task 10 version_translate 会填它。)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_app_version_classify"
down_revision: Union[str, Sequence[str], None] = "0019_community_post_translation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_versions", sa.Column("version_type", sa.String(16), nullable=True))
    op.add_column("app_versions", sa.Column("key_changes_json", sa.Text, nullable=True))
    op.add_column("app_versions", sa.Column("is_significant", sa.Boolean, nullable=True))
    op.add_column("app_versions", sa.Column("classified_at", sa.DateTime, nullable=True))
    op.create_index("idx_app_versions_classified", "app_versions", ["classified_at"])


def downgrade() -> None:
    op.drop_index("idx_app_versions_classified", table_name="app_versions")
    op.drop_column("app_versions", "classified_at")
    op.drop_column("app_versions", "is_significant")
    op.drop_column("app_versions", "key_changes_json")
    op.drop_column("app_versions", "version_type")
