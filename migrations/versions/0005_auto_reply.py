"""Признак ответа бота в режиме «менеджер ушёл».

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет в chat_messages признак автоматического ответа."""
    op.add_column("chat_messages", sa.Column("auto", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Удаляет признак автоматического ответа."""
    op.drop_column("chat_messages", "auto")
