"""Одна оценка на пару «подсказка — менеджер».

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создаёт уникальный частичный индекс по (suggestion_id, manager_id) для оценок с известным менеджером."""
    op.create_index(
        "uq_feedback_suggestion_manager",
        "feedback",
        ["suggestion_id", "manager_id"],
        unique=True,
        postgresql_where=sa.text("manager_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Удаляет индекс."""
    op.drop_index("uq_feedback_suggestion_manager", table_name="feedback")
