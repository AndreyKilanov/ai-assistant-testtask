"""Признак «горячий клиент» у диалога.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет в conversations признак hot."""
    op.add_column("conversations", sa.Column("hot", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Удаляет признак hot."""
    op.drop_column("conversations", "hot")
