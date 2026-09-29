"""Генератор ответов на Groq через LangChain со строгой JSON-схемой ответа и запасной моделью."""

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import groq
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.core.config import Settings
from app.core.errors import LlmUnavailable
from app.domain.generation import GenerationInput, LlmOutput, LlmResult

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 45
LLM_MAX_TOKENS = 1000
LLM_TEMPERATURE = 0.4
LLM_MAX_RETRIES = 3

Chain = tuple[str, Any]
RETRY_RE = re.compile(r"try again in\s+(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)


def parse_retry_after(text: str) -> int | None:
    """Достаёт из сообщения Groq, через сколько секунд освободится лимит («try again in 10m43.2s»).

    Args:
        text: Текст ошибки провайдера.

    Returns:
        Число секунд или None, если в тексте срока нет.
    """
    match = RETRY_RE.search(text)
    if match is None or not any(match.groups()):
        return None
    hours, minutes, seconds = match.groups()
    return int(int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)) + 1


class GroqGenerator:
    """Генератор на Groq (реализует порт Generator).

    Пробует модели по порядку: выбранную менеджером (если выбрана), затем остальные в порядке настроек. У каждой модели
    на бесплатном тарифе свой суточный лимит токенов, поэтому при исчерпании лимита работа продолжается на другой.

    Attributes:
        model_name: Идентификатор основной модели Groq (фактически использованная модель указана в ответе).
        mode: Метка режима в ответе API.
        selector: Асинхронная функция, возвращающая выбранную менеджером модель (None — порядок по умолчанию).
        reporter: Асинхронная функция ``(модель, исход, секунд до снятия лимита)`` для учёта состояния моделей.
    """

    mode = "llm"

    def __init__(self, settings: Settings, chains: Sequence[Chain] | None = None) -> None:
        """Создаёт клиенты моделей.

        Args:
            settings: Настройки с ключом и названиями моделей Groq.
            chains: Готовые пары (модель, цепочка) вместо создаваемых из настроек (для тестов).
        """
        self.model_name = settings.groq_model
        self._chains: list[Chain] = list(chains) if chains is not None else self._build_chains(settings)
        self.selector: Callable[[], Awaitable[str | None]] | None = None
        self.reporter: Callable[[str, str, int | None], Awaitable[None]] | None = None

    @property
    def model_names(self) -> list[str]:
        """Возвращает названия всех подключённых моделей в порядке по умолчанию.

        Returns:
            Основная, запасная и дополнительные модели.
        """
        return [name for name, _ in self._chains]

    @staticmethod
    def _build_chains(settings: Settings) -> list[Chain]:
        """Создаёт цепочки для основной и запасной моделей.

        Args:
            settings: Настройки с ключом и названиями моделей Groq.

        Returns:
            Пары (модель, цепочка со строгой JSON-схемой ответа) в порядке попыток.
        """
        names: list[str] = []
        for name in (settings.groq_model, settings.groq_fallback_model, *settings.groq_extra_models.split(",")):
            name = name.strip()
            if name and name not in names:
                names.append(name)
        chains = []
        for name in names:
            model = ChatGroq(
                model=name,
                api_key=settings.groq_api_key,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                timeout=LLM_TIMEOUT_SECONDS,
                max_retries=LLM_MAX_RETRIES,
            )
            chains.append((name, model.with_structured_output(LlmResult, method="json_schema", include_raw=True)))
        return chains

    async def _report(self, model: str, state: str, retry_after: int | None = None) -> None:
        """Сообщает исход вызова модели; сбой учёта не мешает ответу.

        Args:
            model: Идентификатор модели.
            state: ``ok``, ``rate_limit``, ``unavailable`` или ``bad_format``.
            retry_after: Через сколько секунд освободится лимит.
        """
        if self.reporter is None:
            return
        try:
            await self.reporter(model, state, retry_after)
        except Exception:
            logger.exception("Не удалось записать состояние модели %s", model)

    async def _ordered_chains(self) -> list[Chain]:
        """Ставит выбранную менеджером модель первой; остальные остаются запасными.

        Returns:
            Цепочки в порядке попыток.
        """
        preferred = await self.selector() if self.selector is not None else None
        if not preferred:
            return self._chains
        first = [chain for chain in self._chains if chain[0] == preferred]
        return first + [chain for chain in self._chains if chain[0] != preferred]

    async def generate(self, data: GenerationInput) -> LlmOutput:
        """Вызывает модели по порядку и разбирает ответ по схеме LlmResult.

        Args:
            data: Промпты и найденные записи.

        Returns:
            Разобранный результат и расход токенов; в ``model`` указана модель, давшая ответ.

        Raises:
            LlmUnavailable: Все модели недоступны (лимиты, сеть) или ответили не по схеме.
        """
        messages = [SystemMessage(data.system), HumanMessage(data.user)]
        bad_format = False
        last_error: Exception | None = None
        for name, chain in await self._ordered_chains():
            try:
                raw = await chain.ainvoke(messages)
            except groq.APIError as exc:
                logger.warning("Groq (%s) недоступна: %s", name, exc)
                last_error = exc
                if isinstance(exc, groq.RateLimitError):
                    await self._report(name, "rate_limit", parse_retry_after(str(exc)))
                else:
                    await self._report(name, "unavailable")
                continue
            if raw["parsed"] is None:
                logger.warning("Groq (%s): ответ не соответствует схеме: %s", name, raw.get("parsing_error"))
                bad_format = True
                await self._report(name, "bad_format")
                continue
            await self._report(name, "ok")
            if name != self.model_name:
                logger.info("Ответ получен от запасной модели %s", name)
            usage = raw["raw"].usage_metadata or {}
            return LlmOutput(
                result=raw["parsed"],
                tokens_in=usage.get("input_tokens", 0),
                tokens_out=usage.get("output_tokens", 0),
                model=name,
            )
        if last_error is None and bad_format:
            raise LlmUnavailable("Модель вернула ответ в неожиданном формате, повторите запрос", "bad_format")
        reason = "rate_limit" if isinstance(last_error, groq.RateLimitError) else "unavailable"
        raise LlmUnavailable("Сервис ИИ временно недоступен, попробуйте повторить запрос позже", reason) from last_error
