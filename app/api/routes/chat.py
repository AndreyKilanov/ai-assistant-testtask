"""Публичный чат клиента: свой диалог по неугадываемому токену, без доступа к подсказкам ИИ."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request, status

from app.api.deps import enforce_client_rate_limit, get_container
from app.bootstrap import Container
from app.schemas.chat import (
    ChatMessageOut,
    ClientMessageIn,
    ClientPollOut,
    ClientSessionOut,
    ClientStartIn,
    ContactRequestIn,
    ContactRequestOut,
)
from app.services.conversations import to_client_message

router = APIRouter(prefix="/api/chat", tags=["client-chat"])

Token = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$", description="Токен диалога")]


@router.post("/conversations", response_model=ClientSessionOut, status_code=status.HTTP_201_CREATED)
async def start_conversation(
    payload: ClientStartIn,
    request: Request,
    background: BackgroundTasks,
    container: Annotated[Container, Depends(get_container)],
) -> ClientSessionOut:
    """Начинает диалог (с первым сообщением или без) и возвращает токен, по которому клиент вернётся в чат."""
    await enforce_client_rate_limit(request, container, None)
    conversation, message = await container.conversations.start(payload.client_name, payload.text)
    if message is not None:
        background.add_task(container.conversations.process_client_message, conversation.id, message.id)
    conversation, messages = await container.conversations.client_poll(conversation.token, 0)
    return ClientSessionOut(
        token=conversation.token,
        status=conversation.status,
        contact_requested=conversation.contact_requested_at is not None,
        messages=[to_client_message(m) for m in messages],
        bot_mode=await container.conversations.away.is_enabled(),
    )


@router.get("/conversations/{token}", response_model=ClientSessionOut)
async def get_conversation(token: Token, container: Annotated[Container, Depends(get_container)]) -> ClientSessionOut:
    """Возвращает диалог клиента с историей (для возврата в чат после перезагрузки страницы)."""
    conversation, messages = await container.conversations.client_poll(token, 0)
    return ClientSessionOut(
        token=conversation.token,
        status=conversation.status,
        contact_requested=conversation.contact_requested_at is not None,
        messages=[to_client_message(m) for m in messages],
        bot_mode=await container.conversations.away.is_enabled(),
    )


@router.get("/conversations/{token}/messages", response_model=ClientPollOut)
async def poll_messages(
    token: Token, container: Annotated[Container, Depends(get_container)], after: Annotated[int, Query(ge=0)] = 0
) -> ClientPollOut:
    """Возвращает сообщения диалога с идентификатором больше ``after`` (клиент опрашивает чат раз в пару секунд)."""
    conversation, messages = await container.conversations.client_poll(token, after)
    return ClientPollOut(
        status=conversation.status,
        messages=[to_client_message(m) for m in messages],
        bot_mode=await container.conversations.away.is_enabled(),
    )


@router.post("/conversations/{token}/messages", response_model=ChatMessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    token: Token,
    payload: ClientMessageIn,
    request: Request,
    background: BackgroundTasks,
    container: Annotated[Container, Depends(get_container)],
) -> ChatMessageOut:
    """Принимает сообщение клиента; подсказка ИИ для менеджера (и автоответ, если менеджер ушёл) готовится в фоне."""
    await enforce_client_rate_limit(request, container, token)
    conversation, message = await container.conversations.client_send(token, payload.text)
    background.add_task(container.conversations.process_client_message, conversation.id, message.id)
    return to_client_message(message)


@router.post("/conversations/{token}/contact-request", response_model=ContactRequestOut)
async def request_contact(
    token: Token,
    payload: ContactRequestIn,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> ContactRequestOut:
    """Передаёт менеджеру просьбу связаться: способ связи, контакт и удобное время."""
    await enforce_client_rate_limit(request, container, token)
    await container.conversations.request_contact(token, payload)
    return ContactRequestOut()
