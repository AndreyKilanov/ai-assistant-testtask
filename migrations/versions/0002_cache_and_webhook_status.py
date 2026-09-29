"""Признак попадания в кеш у подсказок и служебные поля событий вебхука.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет suggestions.cache_hit, webhook_events.error и webhook_events.processed_at."""
    op.add_column("suggestions", sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("webhook_events", sa.Column("error", sa.Text()))
    op.add_column("webhook_events", sa.Column("processed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    """Удаляет добавленные столбцы."""
    op.drop_column("webhook_events", "processed_at")
    op.drop_column("webhook_events", "error")
    op.drop_column("suggestions", "cache_hit")
