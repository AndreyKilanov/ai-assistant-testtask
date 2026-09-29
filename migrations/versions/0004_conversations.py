"""Диалоги клиентов с менеджерами и расширенные поля подсказок.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создаёт conversations и chat_messages, добавляет в suggestions намерение, эскалацию и предупреждения."""
    op.add_column("suggestions", sa.Column("purchase_intent", sa.String(20), nullable=False, server_default="none"))
    op.add_column("suggestions", sa.Column("needs_escalation", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "suggestions", sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"))
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("token", sa.String(32), nullable=False, unique=True),
        sa.Column("client_name", sa.String(100)),
        sa.Column("channel", sa.String(20), nullable=False, server_default="web"),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("contact_method", sa.String(20)),
        sa.Column("contact_value", sa.String(200)),
        sa.Column("preferred_time", sa.String(60)),
        sa.Column("contact_comment", sa.Text()),
        sa.Column("contact_requested_at", sa.DateTime(timezone=True)),
        sa.Column("manager_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("unread_by_manager", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_preview", sa.String(160), nullable=False, server_default=""),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_conversations_status_last", "conversations", ["status", "last_message_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "conversation_id", sa.BigInteger(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sender", sa.String(10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("suggestion_id", sa.BigInteger(), sa.ForeignKey("suggestions.id", ondelete="SET NULL")),
        sa.Column("suggestion_state", sa.String(10)),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_conversation", "chat_messages", ["conversation_id", "id"])


def downgrade() -> None:
    """Удаляет диалоги и добавленные столбцы подсказок."""
    op.drop_table("chat_messages")
    op.drop_table("conversations")
    op.drop_column("suggestions", "warnings")
    op.drop_column("suggestions", "needs_escalation")
    op.drop_column("suggestions", "purchase_intent")
