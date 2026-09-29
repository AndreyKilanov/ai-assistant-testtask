"""Сбор метрик по обращениям к ассистенту: декоратор Assistant."""

import time

from app.core.errors import LlmUnavailable, RateLimitExceeded
from app.core.metrics import LATENCY, LLM_TOKENS, RATE_LIMITED, REQUESTS
from app.domain.ports import Assistant, LlmHealthTracker
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse


class MeteredAssistant:
    """Декоратор Assistant: считает обращения, исходы, задержки и токены.

    Стоит снаружи всей цепочки, поэтому видит и ответы из кеша, и отказы по лимитам.

    Attributes:
        inner: Ассистент, чьи вызовы измеряются.
        health: Хранилище состояния модели (None — не вести).
    """

    def __init__(self, inner: Assistant, health: LlmHealthTracker | None = None) -> None:
        """Запоминает измеряемого ассистента.

        Args:
            inner: Ассистент, чьи вызовы измеряются.
            health: Хранилище состояния модели.
        """
        self.inner = inner
        self.health = health

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Вызывает ассистента и фиксирует исход в метриках.

        Args:
            request: Запрос на обработку обращения.

        Returns:
            Ответ ассистента.

        Raises:
            LlmUnavailable: Модель недоступна.
            RateLimitExceeded: Дневной бюджет исчерпан.
        """
        started = time.perf_counter()
        try:
            response = await self.inner.analyze(request)
        except LlmUnavailable as exc:
            REQUESTS.labels(request.mode, "none", "llm_unavailable").inc()
            if self.health is not None:
                await self.health.record_failure("rate_limit" if exc.reason == "rate_limit" else "unavailable")
            raise
        except RateLimitExceeded as exc:
            REQUESTS.labels(request.mode, "none", "rate_limited").inc()
            RATE_LIMITED.labels(exc.scope).inc()
            if self.health is not None and exc.scope == "daily":
                await self.health.record_failure("budget")
            raise
        if self.health is not None and response.cache_status == "miss" and response.mode != "offline":
            await self.health.record_ok(response.model)
        REQUESTS.labels(response.mode, response.cache_status, "ok").inc()
        LATENCY.labels(response.cache_status).observe(time.perf_counter() - started)
        if response.usage.tokens_in or response.usage.tokens_out:
            LLM_TOKENS.labels("in", response.model).inc(response.usage.tokens_in)
            LLM_TOKENS.labels("out", response.model).inc(response.usage.tokens_out)
        return response
