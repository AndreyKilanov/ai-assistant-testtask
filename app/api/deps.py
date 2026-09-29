"""Зависимости FastAPI: доступ к контейнеру, проверка секрета вебхука, лимит обращений."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.bootstrap import Container
from app.core.errors import RateLimitExceeded
from app.core.metrics import RATE_LIMITED
from app.domain.ports import Assistant
from app.services.webhooks import WebhookService

IP_LIMIT_FACTOR = 3
WINDOW_SECONDS = 60
NEW_CONVERSATION_WINDOW_SECONDS = 3600
DAY_SECONDS = 86_400


def get_container(request: Request) -> Container:
    """Возвращает контейнер зависимостей, созданный при старте приложения.

    Args:
        request: Текущий запрос.

    Returns:
        Container из состояния приложения.
    """
    return request.app.state.container


def get_assistant(container: Annotated[Container, Depends(get_container)]) -> Assistant:
    """Возвращает ассистента (с бюджетом, кешем, записью подсказок и метриками).

    Args:
        container: Контейнер зависимостей.

    Returns:
        Ассистент.
    """
    return container.assistant


def get_webhooks(container: Annotated[Container, Depends(get_container)]) -> WebhookService:
    """Возвращает сервис обработки вебхуков.

    Args:
        container: Контейнер зависимостей.

    Returns:
        WebhookService.
    """
    return container.webhooks


def verify_webhook_secret(
    container: Annotated[Container, Depends(get_container)],
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Проверяет общий секрет вебхука в заголовке ``X-Webhook-Secret``.

    Args:
        container: Контейнер зависимостей (из него берётся ожидаемый секрет).
        x_webhook_secret: Секрет из заголовка запроса.

    Raises:
        HTTPException: 401, если секрет не передан или не совпадает.
    """
    expected = container.settings.webhook_secret.get_secret_value().encode()
    if x_webhook_secret is None or not hmac.compare_digest(x_webhook_secret.encode(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный секрет вебхука")


def require_manager(
    container: Annotated[Container, Depends(get_container)],
    x_manager_token: Annotated[str | None, Header()] = None,
) -> None:
    """Проверяет код доступа менеджера в заголовке ``X-Manager-Token``.

    Закрывает консоль менеджера и ИИ-эндпоинты от клиентов, которые открывают публичный экран чата.

    Args:
        container: Контейнер зависимостей (из него берётся ожидаемый код).
        x_manager_token: Код доступа из заголовка запроса.

    Raises:
        HTTPException: 401, если код не передан или не совпадает.
    """
    expected = container.settings.manager_token.get_secret_value().encode()
    if x_manager_token is None or not hmac.compare_digest(x_manager_token.encode(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен код доступа менеджера")


def client_ip(request: Request) -> str:
    """Возвращает IP-адрес клиента (за прокси — только если uvicorn доверяет ему через FORWARDED_ALLOW_IPS).

    Args:
        request: Текущий запрос.

    Returns:
        IP-адрес или ``unknown``, если его нет.
    """
    return request.client.host if request.client else "unknown"


async def _enforce(container: Container, key: str, limit: int, window_seconds: int, message: str) -> None:
    """Учитывает обращение по ключу и отказывает, если лимит превышен.

    Args:
        container: Контейнер зависимостей (ограничитель).
        key: Ключ счётчика.
        limit: Максимум обращений за окно.
        window_seconds: Длина окна в секундах.
        message: Сообщение об отказе для клиента.

    Raises:
        RateLimitExceeded: Лимит превышен.
    """
    decision = await container.rate_limiter.hit(key, limit, window_seconds)
    if not decision.allowed:
        RATE_LIMITED.labels("client").inc()
        raise RateLimitExceeded("client", decision.retry_after, message)


async def enforce_client_rate_limit(request: Request, container: Container, lead_id: str | None) -> None:
    """Ограничивает частоту обращений: по сделке и, втрое мягче, по IP-адресу клиента.

    Лимит по IP нужен на случай, когда спамер подставляет разные ``lead_id``.

    Args:
        request: Текущий запрос (из него берётся IP).
        container: Контейнер зависимостей (ограничитель и настройки).
        lead_id: Идентификатор сделки из тела запроса.

    Raises:
        RateLimitExceeded: Превышен лимит обращений в минуту.
    """
    limit = container.settings.client_rate_limit_per_minute
    message = "Слишком много обращений, повторите позже"
    await _enforce(container, f"rl:ip:{client_ip(request)}", limit * IP_LIMIT_FACTOR, WINDOW_SECONDS, message)
    if lead_id:
        await _enforce(container, f"rl:lead:{lead_id}", limit, WINDOW_SECONDS, message)


async def enforce_new_conversation_limit(request: Request, container: Container) -> None:
    """Ограничивает число новых диалогов с одного IP-адреса в час.

    Без этого анонимный клиент мог бы забить входящие менеджера пустыми диалогами.

    Args:
        request: Текущий запрос (из него берётся IP).
        container: Контейнер зависимостей (ограничитель и настройки).

    Raises:
        RateLimitExceeded: Превышен часовой лимит новых диалогов.
    """
    await _enforce(
        container,
        f"rl:new-conversation:{client_ip(request)}",
        container.settings.client_new_conversations_per_hour,
        NEW_CONVERSATION_WINDOW_SECONDS,
        "Слишком много новых диалогов, повторите позже",
    )


async def enforce_client_daily_limit(request: Request, container: Container) -> None:
    """Ограничивает число сообщений клиента в сутки с одного IP-адреса.

    Каждое сообщение может стоить запроса к модели, а дневной бюджет модели общий: один адрес не должен выбирать его
    целиком у остальных клиентов.

    Args:
        request: Текущий запрос (из него берётся IP).
        container: Контейнер зависимостей (ограничитель и настройки).

    Raises:
        RateLimitExceeded: Превышен суточный лимит сообщений.
    """
    await _enforce(
        container,
        f"rl:messages-day:{client_ip(request)}",
        container.settings.client_daily_messages_per_ip,
        DAY_SECONDS,
        "Достигнут суточный лимит сообщений, повторите позже",
    )
