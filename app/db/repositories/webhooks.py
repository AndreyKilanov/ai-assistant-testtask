"""Репозиторий событий вебхука (таблица ``webhook_events``)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.db.models import WebhookEvent
from app.db.session import Sessionmaker
from app.domain.ports import WebhookEventRecord


class WebhookEventRepository:
    """Хранилище событий вебхука в таблице ``webhook_events`` (реализует порт WebhookEventStore).

    Attributes:
        sessionmaker: Фабрика асинхронных сессий.
    """

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        """Запоминает фабрику сессий.

        Args:
            sessionmaker: Фабрика асинхронных сессий SQLAlchemy.
        """
        self.sessionmaker = sessionmaker

    async def create(self, event_id: str, payload: dict[str, Any]) -> bool:
        """Сохраняет событие, если его ещё не было (уникальный ``event_id``).

        Args:
            event_id: Идентификатор события.
            payload: Тело события.

        Returns:
            True, если событие новое; False, если такое уже принималось.
        """
        stmt = (
            insert(WebhookEvent)
            .values(event_id=event_id, payload=payload)
            .on_conflict_do_nothing(index_elements=["event_id"])
            .returning(WebhookEvent.id)
        )
        async with self.sessionmaker() as session:
            inserted = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
        return inserted is not None

    async def get(self, event_id: str) -> WebhookEventRecord | None:
        """Возвращает событие.

        Args:
            event_id: Идентификатор события.

        Returns:
            Событие или None.
        """
        async with self.sessionmaker() as session:
            row = (
                await session.execute(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
            ).scalar_one_or_none()
        return None if row is None else WebhookEventRecord(row.event_id, row.payload, row.status)

    async def set_status(self, event_id: str, status: str, error: str | None = None) -> None:
        """Обновляет статус обработки.

        Args:
            event_id: Идентификатор события.
            status: Новый статус.
            error: Текст ошибки, если есть.
        """
        values: dict[str, Any] = {"status": status, "error": error}
        if status == "processed":
            values["processed_at"] = datetime.now(UTC)
        async with self.sessionmaker() as session:
            await session.execute(update(WebhookEvent).where(WebhookEvent.event_id == event_id).values(**values))
            await session.commit()

    async def delete(self, event_id: str) -> None:
        """Удаляет событие, чтобы повторная доставка была принята заново.

        Args:
            event_id: Идентификатор события.
        """
        async with self.sessionmaker() as session:
            await session.execute(delete(WebhookEvent).where(WebhookEvent.event_id == event_id))
            await session.commit()
