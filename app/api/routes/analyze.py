"""Эндпоинт подготовки ответа клиенту и подсказки менеджеру."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import enforce_client_rate_limit, get_container, require_manager
from app.bootstrap import Container
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/api", tags=["assistant"], dependencies=[Depends(require_manager)])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest, request: Request, container: Annotated[Container, Depends(get_container)]
) -> AnalyzeResponse:
    """Готовит ответ клиенту и подсказку по допродаже для менеджера.

    Частота обращений ограничена по сделке и по IP (429 с Retry-After); повторяющиеся вопросы отдаются из кеша.
    """
    await enforce_client_rate_limit(request, container, payload.lead_id)
    return await container.assistant.analyze(payload)
