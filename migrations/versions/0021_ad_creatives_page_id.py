"""add page_id column to ad_creatives

Revision ID: 0021_ad_creatives_page_id
Revises: 0020_app_version_classify
Create Date: 2026-05-08 16:00:00.000000

之前 fb_adlib scraper 用 keyword 模糊匹配 q=<竞品名>，结果搜 SofaScore 抓回 30+
条沙发卖家广告（"Sofa" 命中），AllFootball 抓回 football 关键字相关的杂货广告。
真正属于该竞品的广告 < 10%。

方案 B 落地：
- 改 scraper 优先用 view_all_page_id=<page_id> 精确匹配（100% 该 page 的广告）
- competitors.json 加 fb_page_id 字段，由 discover-pages CLI 自动填
- ad_creatives 表加 page_id 列：每条广告记录抓时实际命中的广告主 page_id，
  用作 audit / 后续按 page_id 重组数据 / discover-pages 的反向输入

page_id 字段允许 NULL（discover 流程未跑或老数据回填前是空）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_ad_creatives_page_id"
down_revision: Union[str, Sequence[str], None] = "0020_app_version_classify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ad_creatives", sa.Column("page_id", sa.String(32), nullable=True))
    op.create_index("idx_ad_creatives_page_id", "ad_creatives", ["page_id"])


def downgrade() -> None:
    op.drop_index("idx_ad_creatives_page_id", table_name="ad_creatives")
    op.drop_column("ad_creatives", "page_id")
