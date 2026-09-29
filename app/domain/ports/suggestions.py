"""Порты подсказок: хранилище выданных подсказок, оценки менеджеров и статистика."""

from typing import Protocol

from app.schemas.analyze import AnalyzeResponse
from app.schemas.stats import StatsResponse


class SuggestionStore(Protocol):
    """Хранилище выданных подсказок."""

    async def save(self, lead_id: str | None, client_message: str, response: AnalyzeResponse) -> int | None:
        """Сохраняет подсказку.

        Args:
            lead_id: Идентификатор сделки.
            client_message: Сообщение клиента.
            response: Готовый ответ.

        Returns:
            Идентификатор записи или None, если сохранить не удалось.
        """
        ...


class FeedbackStore(Protocol):
    """Хранилище оценок менеджеров."""

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
        ...


class StatsProvider(Protocol):
    """Источник сводной статистики."""

    async def today(self) -> StatsResponse:
        """Считает статистику за текущие сутки (UTC).

        Returns:
            Сводка по подсказкам, токенам, кешу и оценкам.
        """
        ...
