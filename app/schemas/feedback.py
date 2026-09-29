"""Схемы оценки подсказки менеджером."""

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """Оценка менеджера.

    Attributes:
        suggestion_id: Идентификатор подсказки из ответа ``/api/analyze``.
        rating: 1 — подсказка полезна, -1 — не полезна.
        comment: Комментарий менеджера (что не так, как надо было ответить).
        manager_id: Идентификатор менеджера; повторная оценка того же менеджера обновляет предыдущую.
    """

    suggestion_id: int = Field(gt=0)
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)
    manager_id: str | None = Field(default=None, min_length=1, max_length=100)


class FeedbackResponse(BaseModel):
    """Подтверждение сохранения оценки.

    Attributes:
        feedback_id: Идентификатор сохранённой оценки.
        status: Всегда ``saved``.
    """

    feedback_id: int
    status: Literal["saved"] = "saved"
