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
    ip = request.client.host if request.client else "unknown"
    checks = [(f"rl:ip:{ip}", limit * IP_LIMIT_FACTOR)]
    if lead_id:
        checks.append((f"rl:lead:{lead_id}", limit))
    for key, key_limit in checks:
        decision = await container.rate_limiter.hit(key, key_limit, WINDOW_SECONDS)
        if not decision.allowed:
            RATE_LIMITED.labels("client").inc()
            raise RateLimitExceeded("client", decision.retry_after, "Слишком много обращений, повторите позже")
