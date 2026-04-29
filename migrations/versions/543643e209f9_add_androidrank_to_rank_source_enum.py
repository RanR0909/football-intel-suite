"""add androidrank to rank_source enum

Revision ID: 543643e209f9
Revises: afec0ab9235a
Create Date: 2026-04-29 15:01:37.208454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '543643e209f9'
down_revision: Union[str, Sequence[str], None] = 'afec0ab9235a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add 'androidrank' to rank_source enum.

    Alembic autogen 不识别 MySQL Enum 列变更，需手写 ALTER COLUMN。
    """
    op.execute(
        "ALTER TABLE market_rank_snapshots "
        "MODIFY COLUMN source ENUM('appmagic', 'appstore_rank', 'sensor_tower', 'androidrank') NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE market_rank_snapshots "
        "MODIFY COLUMN source ENUM('appmagic', 'appstore_rank', 'sensor_tower') NOT NULL"
    )
