"""Оценка подсказок менеджерами."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_container, require_manager
from app.bootstrap import Container
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/api", tags=["feedback"], dependencies=[Depends(require_manager)])


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackRequest, container: Annotated[Container, Depends(get_container)]
) -> FeedbackResponse:
    """Сохраняет оценку подсказки (1 — полезна, -1 — нет) и комментарий менеджера.

    Повторная оценка того же менеджера обновляет предыдущую; для несуществующей подсказки возвращается 404.
    """
    return await container.feedback.submit(payload)
