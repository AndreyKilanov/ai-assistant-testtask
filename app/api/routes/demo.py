"""Демо-режим: переключатель экранов и вход менеджера без ввода кода (только при ``DEMO_MODE=true``)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import enforce_client_rate_limit, get_container
from app.bootstrap import Container

router = APIRouter(prefix="/api/demo", tags=["demo"])


class DemoConfig(BaseModel):
    """Настройки демо-режима для интерфейса.

    Attributes:
        enabled: Демо-режим включён: показывать переключатель экранов и входить в консоль автоматически.
    """

    enabled: bool


class DemoSession(BaseModel):
    """Вход менеджера в демо-режиме.

    Attributes:
        token: Код доступа менеджера.
    """

    token: str


@router.get("/config", response_model=DemoConfig)
async def demo_config(container: Annotated[Container, Depends(get_container)]) -> DemoConfig:
    """Сообщает интерфейсу, включён ли демо-режим (публично, секретов не содержит)."""
    return DemoConfig(enabled=container.settings.demo_mode)


@router.post("/manager-session", response_model=DemoSession)
async def demo_manager_session(
    request: Request, container: Annotated[Container, Depends(get_container)]
) -> DemoSession:
    """Выдаёт код менеджера для автоматического входа в консоль; без ``DEMO_MODE`` отвечает 404.

    Только для демонстрации на локальной машине: включённый режим делает консоль доступной любому, кто открыл страницу.
    """
    if not container.settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Демо-режим выключен")
    await enforce_client_rate_limit(request, container, None)
    return DemoSession(token=container.settings.manager_token.get_secret_value())
