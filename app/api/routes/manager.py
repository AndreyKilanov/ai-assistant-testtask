"""Консоль менеджера: входящие, история переписки, карточка клиента, ответы и подсказки ИИ."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, status

from app.api.deps import get_container, require_manager
from app.bootstrap import Container
from app.schemas.analyze import AnalyzeResponse
from app.schemas.chat import (
    AwayModeIn,
    AwayModeOut,
    ConversationDetail,
    ConversationListOut,
    ConversationStatus,
    ConversationSummary,
    ManagerMessageIn,
    ManagerMessageOut,
    NoteIn,
    StatusIn,
)
from app.schemas.stats import ModelChoiceIn, ModelStatus
from app.services.conversations import LIST_LIMIT, to_manager_message, to_summary

router = APIRouter(prefix="/api/manager", tags=["manager"], dependencies=[Depends(require_manager)])

ConversationId = Annotated[int, Path(gt=0)]
MAX_LIST_LIMIT = 500


@router.get("/session")
async def session_check() -> dict[str, bool]:
    """Проверяет код доступа менеджера (используется при входе в консоль)."""
    return {"ok": True}


@router.get("/conversations", response_model=ConversationListOut)
async def list_conversations(
    container: Annotated[Container, Depends(get_container)],
    status_filter: Annotated[ConversationStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = LIST_LIMIT,
) -> ConversationListOut:
    """Возвращает входящие: новые и просящие связаться выше остальных; фильтр по статусу, поиск и размер выдачи.

    Если диалогов больше ``limit``, в ответе ``has_more = true``: запросите больше.
    """
    return await container.conversations.list_for_manager(status_filter, q, limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: ConversationId, container: Annotated[Container, Depends(get_container)]
) -> ConversationDetail:
    """Возвращает диалог: переписку, карточку клиента, заметку и подсказку ИИ. Диалог отмечается прочитанным."""
    return await container.conversations.detail(conversation_id, expose_client_token=container.settings.demo_mode)


@router.post(
    "/conversations/{conversation_id}/messages", response_model=ManagerMessageOut, status_code=status.HTTP_201_CREATED
)
async def send_message(
    conversation_id: ConversationId, payload: ManagerMessageIn, container: Annotated[Container, Depends(get_container)]
) -> ManagerMessageOut:
    """Отправляет ответ менеджера клиенту; если он основан на подсказке ИИ, сохраняется признак правки текста."""
    message = await container.conversations.manager_send(conversation_id, payload.text, payload.suggestion_id)
    return to_manager_message(message)


@router.post("/conversations/{conversation_id}/status", response_model=ConversationSummary)
async def set_status(
    conversation_id: ConversationId, payload: StatusIn, container: Annotated[Container, Depends(get_container)]
) -> ConversationSummary:
    """Меняет статус диалога."""
    return to_summary(await container.conversations.set_status(conversation_id, payload.status))


@router.put("/conversations/{conversation_id}/note", response_model=ConversationSummary)
async def set_note(
    conversation_id: ConversationId, payload: NoteIn, container: Annotated[Container, Depends(get_container)]
) -> ConversationSummary:
    """Сохраняет внутреннюю заметку менеджера (клиент её не видит)."""
    return to_summary(await container.conversations.set_note(conversation_id, payload.note))


@router.post("/conversations/{conversation_id}/suggestion", response_model=AnalyzeResponse)
async def regenerate_suggestion(
    conversation_id: ConversationId, container: Annotated[Container, Depends(get_container)]
) -> AnalyzeResponse:
    """Заново готовит подсказку ИИ к последнему сообщению клиента (429 при исчерпанном бюджете, 503 при сбое модели)."""
    response = await container.conversations.generate_suggestion(conversation_id, raise_errors=True, refresh=True)
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "В диалоге нет сообщений клиента для подсказки")
    return response


@router.get("/away", response_model=AwayModeOut)
async def get_away(container: Annotated[Container, Depends(get_container)]) -> AwayModeOut:
    """Возвращает, включён ли режим «менеджер ушёл» (бот отвечает на все входящие сам)."""
    return AwayModeOut(enabled=await container.conversations.away.is_enabled())


@router.put("/away", response_model=AwayModeOut)
async def set_away(
    payload: AwayModeIn, background: BackgroundTasks, container: Annotated[Container, Depends(get_container)]
) -> AwayModeOut:
    """Включает или выключает режим «менеджер ушёл»; при включении бот отвечает на сообщения, ждавшие менеджера."""
    await container.conversations.away.set_enabled(payload.enabled)
    if payload.enabled:
        background.add_task(container.conversations.answer_backlog)
    return AwayModeOut(enabled=payload.enabled)


@router.get("/model-status", response_model=ModelStatus)
async def model_status(container: Annotated[Container, Depends(get_container)]) -> ModelStatus:
    """Возвращает состояние языковой модели: какая подключена и работает ли она (лимиты, недоступность)."""
    return await container.llm_health.snapshot()


@router.put("/model", response_model=ModelStatus)
async def choose_model(payload: ModelChoiceIn, container: Annotated[Container, Depends(get_container)]) -> ModelStatus:
    """Выбирает модель, которая отвечает первой (остальные остаются запасными); ``null`` — автоматический порядок."""
    try:
        await container.llm_health.set_selected(payload.model)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Такой модели нет в списке") from None
    return await container.llm_health.snapshot()
