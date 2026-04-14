"""add build_dir to sites

Revision ID: a1b2c3d4e5f6
Revises: 8220336cb266
Create Date: 2026-04-14 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '8220336cb266'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add build_dir column to sites table."""
    op.add_column('sites', sa.Column('build_dir', sa.String(length=512), nullable=True))


def downgrade() -> None:
    """Remove build_dir column from sites table."""
    op.drop_column('sites', 'build_dir')
