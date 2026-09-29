"""Индекс по времени сообщений для разбора неотвеченных диалогов.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создаёт индекс ix_chat_messages_created_at без блокировки записи."""
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_chat_messages_created_at",
            "chat_messages",
            ["created_at"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    """Удаляет индекс ix_chat_messages_created_at."""
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_chat_messages_created_at",
            table_name="chat_messages",
            postgresql_concurrently=True,
            if_exists=True,
        )
