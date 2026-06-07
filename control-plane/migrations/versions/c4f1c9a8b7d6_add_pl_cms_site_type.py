"""add pl_cms site type

Revision ID: c4f1c9a8b7d6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-07 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f1c9a8b7d6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_SITE_TYPE = sa.Enum('static', 'php', 'node', 'python', 'proxy', 'wordpress', name='sitetype')
_NEW_SITE_TYPE = sa.Enum('static', 'php', 'node', 'python', 'proxy', 'wordpress', 'pl_cms', name='sitetype')


def upgrade() -> None:
    """Add the pl_cms value to the sites.site_type enum."""
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("ALTER TYPE sitetype ADD VALUE IF NOT EXISTS 'pl_cms'")
        return

    with op.batch_alter_table('sites', recreate='always') as batch_op:
        batch_op.alter_column(
            'site_type',
            existing_type=_OLD_SITE_TYPE,
            type_=_NEW_SITE_TYPE,
            existing_nullable=False,
        )


def downgrade() -> None:
    """Remove the pl_cms value from the sites.site_type enum."""
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("ALTER TABLE sites ALTER COLUMN site_type TYPE TEXT USING site_type::text")
        op.execute("DROP TYPE sitetype")
        op.execute("CREATE TYPE sitetype AS ENUM ('static', 'php', 'node', 'python', 'proxy', 'wordpress')")
        op.execute("ALTER TABLE sites ALTER COLUMN site_type TYPE sitetype USING site_type::sitetype")
        return

    with op.batch_alter_table('sites', recreate='always') as batch_op:
        batch_op.alter_column(
            'site_type',
            existing_type=_NEW_SITE_TYPE,
            type_=_OLD_SITE_TYPE,
            existing_nullable=False,
        )
