"""Приём оценок менеджеров: основа для улучшения промптов и базы знаний."""

import logging

from app.core.metrics import FEEDBACK
from app.domain.ports import FeedbackStore
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

logger = logging.getLogger(__name__)


class FeedbackService:
    """Сохраняет оценки подсказок.

    Attributes:
        store: Хранилище оценок.
    """

    def __init__(self, store: FeedbackStore) -> None:
        """Запоминает хранилище.

        Args:
            store: Хранилище оценок.
        """
        self.store = store

    async def submit(self, payload: FeedbackRequest) -> FeedbackResponse:
        """Сохраняет оценку менеджера.

        Args:
            payload: Оценка и комментарий.

        Returns:
            Подтверждение с идентификатором оценки.

        Raises:
            SuggestionNotFound: Подсказки с таким идентификатором нет.
        """
        feedback_id = await self.store.save(payload.suggestion_id, payload.rating, payload.comment, payload.manager_id)
        FEEDBACK.labels("up" if payload.rating == 1 else "down").inc()
        logger.info("Оценка %s подсказки %s сохранена", payload.rating, payload.suggestion_id)
        return FeedbackResponse(feedback_id=feedback_id)
