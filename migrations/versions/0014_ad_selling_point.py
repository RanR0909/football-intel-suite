"""ad_creatives 加 selling_points / audience / tone (task #7 ad_selling_point)

Revision ID: 0014_ad_selling_point
Revises: 0013_community_topic
Create Date: 2026-05-06 11:10:00.000000

任务 7 (ad_selling_point) 给每条 fb_adlib 创意打：
- selling_points (JSON, 多选 8 类: live_score / local_league / ai_prediction /
  betting_funnel / data_depth / free_app / premium_subscription / content_unique)
- audience (单选 5 类: casual_fan / hardcore_fan / bettor / data_geek / local_fan)
- tone (单选 4 类: urgent / narrative / comparative / numeric)

铁律 4: 已分类 (selling_classified_at IS NOT NULL) 的创意不重复跑，
       同 ad_id 但 text 变化才重跑（spec 缓存策略）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_ad_selling_point"
down_revision: Union[str, Sequence[str], None] = "0013_community_topic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ad_creatives", sa.Column("selling_points", sa.Text()))            # JSON ["live_score","free_app"]
    op.add_column("ad_creatives", sa.Column("audience", sa.String(length=32)))
    op.add_column("ad_creatives", sa.Column("tone", sa.String(length=16)))
    op.add_column("ad_creatives", sa.Column("selling_classified_at", sa.DateTime()))
    op.add_column("ad_creatives", sa.Column("selling_confidence", sa.Numeric(3, 2)))
    op.create_index("idx_ad_audience", "ad_creatives", ["audience"])
    op.create_index("idx_ad_tone", "ad_creatives", ["tone"])
    op.create_index("idx_ad_selling_classified_at", "ad_creatives", ["selling_classified_at"])


def downgrade() -> None:
    op.drop_index("idx_ad_selling_classified_at", table_name="ad_creatives")
    op.drop_index("idx_ad_tone", table_name="ad_creatives")
    op.drop_index("idx_ad_audience", table_name="ad_creatives")
    op.drop_column("ad_creatives", "selling_confidence")
    op.drop_column("ad_creatives", "selling_classified_at")
    op.drop_column("ad_creatives", "tone")
    op.drop_column("ad_creatives", "audience")
    op.drop_column("ad_creatives", "selling_points")
