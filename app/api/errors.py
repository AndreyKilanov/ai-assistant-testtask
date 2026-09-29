"""Соответствие доменных ошибок HTTP-ответам."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import (
    ConversationNotFound,
    LlmUnavailable,
    QueueUnavailable,
    RateLimitExceeded,
    SuggestionNotFound,
)

RETRY_AFTER_SECONDS = "20"


def register_exception_handlers(application: FastAPI) -> None:
    """Подключает обработчики доменных ошибок.

    Args:
        application: Приложение FastAPI.
    """

    def unavailable(exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": RETRY_AFTER_SECONDS})

    @application.exception_handler(LlmUnavailable)
    async def llm_unavailable_handler(_: Request, exc: LlmUnavailable) -> JSONResponse:
        """Отвечает 503, когда модель недоступна."""
        return unavailable(exc)

    @application.exception_handler(QueueUnavailable)
    async def queue_unavailable_handler(_: Request, exc: QueueUnavailable) -> JSONResponse:
        """Отвечает 503, когда очередь недоступна: AmoCRM повторит доставку вебхука."""
        return unavailable(exc)

    @application.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        """Отвечает 429 с заголовком Retry-After, когда сработал лимит запросов."""
        return JSONResponse({"detail": str(exc)}, status_code=429, headers={"Retry-After": str(exc.retry_after)})

    @application.exception_handler(SuggestionNotFound)
    async def suggestion_not_found_handler(_: Request, exc: SuggestionNotFound) -> JSONResponse:
        """Отвечает 404, когда оценивается несуществующая подсказка."""
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @application.exception_handler(ConversationNotFound)
    async def conversation_not_found_handler(_: Request, exc: ConversationNotFound) -> JSONResponse:
        """Отвечает 404, когда диалога с таким токеном или идентификатором нет."""
        return JSONResponse({"detail": str(exc)}, status_code=404)
