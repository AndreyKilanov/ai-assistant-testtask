"""Репозитории: доступ к таблицам подсказок и событий вебхука."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, literal_column, select, text, update
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import SuggestionNotFound
from app.db.models import Feedback, KbDocument, Suggestion, WebhookEvent
from app.domain.ports import WebhookEventRecord
from app.schemas.analyze import AnalyzeResponse, SourceRef, Usage
from app.schemas.stats import StatsResponse

logger = logging.getLogger(__name__)

Sessionmaker = async_sessionmaker[AsyncSession]


class SuggestionRepository:
    """Хранилище подсказок в таблице ``suggestions`` (реализует порт SuggestionStore).

    Attributes:
        sessionmaker: Фабрика асинхронных сессий.
    """

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        """Запоминает фабрику сессий.

        Args:
            sessionmaker: Фабрика асинхронных сессий SQLAlchemy.
        """
        self.sessionmaker = sessionmaker

    async def save(self, lead_id: str | None, client_message: str, response: AnalyzeResponse) -> int | None:
        """Сохраняет подсказку; сбой БД не ломает ответ пользователю.

        Args:
            lead_id: Идентификатор сделки.
            client_message: Сообщение клиента.
            response: Готовый ответ.

        Returns:
            Идентификатор записи или None при ошибке БД.
        """
        row = Suggestion(
            lead_id=lead_id,
            client_message=client_message,
            reply=response.reply,
            upsell_hint=response.upsell_hint,
            analysis=response.analysis,
            sources=[source.model_dump() for source in response.sources],
            priority=response.priority,
            purchase_intent=response.purchase_intent,
            needs_escalation=response.needs_escalation,
            warnings=response.warnings,
            mode=response.mode,
            cache_hit=response.cache_status == "hit",
            model=response.model,
            prompt_version=response.prompt_version,
            tokens_in=response.usage.tokens_in,
            tokens_out=response.usage.tokens_out,
            latency_ms=response.usage.latency_ms,
        )
        try:
            async with self.sessionmaker() as session:
                session.add(row)
                await session.commit()
                return row.id
        except SQLAlchemyError:
            logger.exception("Не удалось сохранить подсказку")
            return None

    async def get(self, suggestion_id: int) -> AnalyzeResponse | None:
        """Возвращает сохранённую подсказку в виде ответа API.

        Args:
            suggestion_id: Идентификатор подсказки.

        Returns:
            Подсказка или None, если её нет.
        """
        async with self.sessionmaker() as session:
            row = await session.get(Suggestion, suggestion_id)
        if row is None:
            return None
        return AnalyzeResponse(
            suggestion_id=row.id,
            reply=row.reply,
            upsell_hint=row.upsell_hint,
            priority=row.priority,
            purchase_intent=row.purchase_intent,
            needs_escalation=row.needs_escalation,
            analysis=row.analysis,
            sources=[SourceRef(**source) for source in row.sources],
            warnings=list(row.warnings),
            mode=row.mode,
            model=row.model,
            prompt_version=row.prompt_version,
            usage=Usage(tokens_in=row.tokens_in, tokens_out=row.tokens_out, latency_ms=row.latency_ms),
            cache_status="hit" if row.cache_hit else "miss",
        )


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


async def knowledge_version(sessionmaker: Sessionmaker) -> str:
    """Возвращает версию базы знаний: свёртка хешей всех записей из ``kb_documents``.

    Версия входит в ключ кеша ответов: после переиндексации базы старые закешированные ответы перестают
    использоваться.

    Args:
        sessionmaker: Фабрика асинхронных сессий.

    Returns:
        Короткая строка-версия; ``empty``, если база ещё не проиндексирована.
    """
    hashes = func.string_agg(KbDocument.content_hash, aggregate_order_by(literal_column("''"), KbDocument.slug))
    stmt = select(func.md5(hashes))
    async with sessionmaker() as session:
        digest = (await session.execute(stmt)).scalar_one_or_none()
    return digest[:12] if digest else "empty"


class FeedbackRepository:
    """Хранилище оценок менеджеров в таблице ``feedback`` (реализует порт FeedbackStore).

    Attributes:
        sessionmaker: Фабрика асинхронных сессий.
    """

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        """Запоминает фабрику сессий.

        Args:
            sessionmaker: Фабрика асинхронных сессий SQLAlchemy.
        """
        self.sessionmaker = sessionmaker

    async def save(self, suggestion_id: int, rating: int, comment: str | None, manager_id: str | None) -> int:
        """Сохраняет оценку; повторная оценка того же менеджера обновляет прежнюю.

        Args:
            suggestion_id: Оцениваемая подсказка.
            rating: 1 или -1.
            comment: Комментарий менеджера.
            manager_id: Идентификатор менеджера.

        Returns:
            Идентификатор оценки.

        Raises:
            SuggestionNotFound: Подсказки с таким идентификатором нет.
        """
        values = {"suggestion_id": suggestion_id, "rating": rating, "comment": comment, "manager_id": manager_id}
        stmt = insert(Feedback).values(**values)
        if manager_id is not None:
            stmt = stmt.on_conflict_do_update(
                index_elements=["suggestion_id", "manager_id"],
                index_where=Feedback.manager_id.isnot(None),
                set_={"rating": rating, "comment": comment, "created_at": func.now()},
            )
        async with self.sessionmaker() as session:
            if await session.scalar(select(Suggestion.id).where(Suggestion.id == suggestion_id)) is None:
                raise SuggestionNotFound(f"Подсказка {suggestion_id} не найдена")
            feedback_id = (await session.execute(stmt.returning(Feedback.id))).scalar_one()
            await session.commit()
        return feedback_id


class StatsRepository:
    """Сводная статистика по таблицам ``suggestions`` и ``feedback`` (реализует порт StatsProvider).

    Attributes:
        sessionmaker: Фабрика асинхронных сессий.
        daily_llm_limit: Дневной бюджет обращений к модели (для отчёта).
    """

    def __init__(self, sessionmaker: Sessionmaker, daily_llm_limit: int) -> None:
        """Запоминает зависимости.

        Args:
            sessionmaker: Фабрика асинхронных сессий SQLAlchemy.
            daily_llm_limit: Дневной бюджет обращений к модели.
        """
        self.sessionmaker = sessionmaker
        self.daily_llm_limit = daily_llm_limit

    async def today(self) -> StatsResponse:
        """Считает статистику за текущие сутки (UTC).

        Returns:
            Сводка по подсказкам, токенам, кешу и оценкам.
        """
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        suggestions = text(
            """
            select count(*) as total,
                   count(*) filter (where cache_hit) as hits,
                   coalesce(sum(tokens_in), 0) as tokens_in,
                   coalesce(sum(tokens_out), 0) as tokens_out,
                   avg(latency_ms) filter (where not cache_hit) as avg_llm,
                   avg(latency_ms) filter (where cache_hit) as avg_cache
            from suggestions where created_at >= :start
            """
        )
        feedback = text(
            """
            select count(*) filter (where rating = 1) as up, count(*) filter (where rating = -1) as down
            from feedback where created_at >= :start
            """
        )
        async with self.sessionmaker() as session:
            row = (await session.execute(suggestions, {"start": start})).one()
            votes = (await session.execute(feedback, {"start": start})).one()
        return StatsResponse(
            date=start.date().isoformat(),
            requests_total=row.total,
            cache_hits=row.hits,
            llm_calls=row.total - row.hits,
            cache_hit_ratio=round(row.hits / row.total, 3) if row.total else 0.0,
            tokens_in=int(row.tokens_in),
            tokens_out=int(row.tokens_out),
            avg_latency_llm_ms=None if row.avg_llm is None else round(float(row.avg_llm), 1),
            avg_latency_cache_ms=None if row.avg_cache is None else round(float(row.avg_cache), 1),
            daily_llm_limit=self.daily_llm_limit,
            feedback_positive=votes.up,
            feedback_negative=votes.down,
        )
