"""Репозиторий подсказок (таблица ``suggestions``)."""

import logging

from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Suggestion
from app.db.session import Sessionmaker
from app.schemas.analyze import AnalyzeResponse, SourceRef, Usage

logger = logging.getLogger(__name__)


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
