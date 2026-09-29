"""Кеширование ответов ассистента: повторяющиеся вопросы не должны тратить запросы к модели.

Кеш подключается декоратором поверх любого Assistant. Ключ строится по нормализованному вопросу и последнему обмену
репликами, а не по всей истории: иначе у клиента, который повторяет один вопрос, история росла бы с каждым
повтором и ключ каждый раз был бы новым. Одинаковые запросы, пришедшие одновременно, сливаются в один вызов модели.
"""

import asyncio
import hashlib
import json
import logging
import re
import time

from app.domain.ports import Assistant, ResponseCache
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse, Usage

logger = logging.getLogger(__name__)

TRAILING_PUNCTUATION = " ?!.,;:…"
WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Приводит реплику к виду, не зависящему от регистра, пробелов и знаков в конце.

    Args:
        text: Исходный текст.

    Returns:
        Нормализованный текст: «Сколько стоит?» и «сколько  стоит» дают одну строку.
    """
    return WHITESPACE_RE.sub(" ", text.casefold()).strip(TRAILING_PUNCTUATION)


def build_cache_key(request: AnalyzeRequest, namespace: str, history_turns: int) -> str:
    """Строит ключ кеша по смыслу запроса.

    В ключ входят режим, нормализованное сообщение и последние ``history_turns`` реплик; идентификатор сделки не
    входит: ответ на один и тот же вопрос не зависит от того, из какой сделки он пришёл.

    Args:
        request: Запрос на обработку обращения.
        namespace: Версия окружения ответа: промпты, модель и версия базы знаний. Смена любой из них
            автоматически делает старые записи кеша недостижимыми.
        history_turns: Сколько последних реплик диалога учитывать.

    Returns:
        Ключ вида ``analyze:<namespace>:<sha256>``.
    """
    recent = request.history[-history_turns:] if history_turns > 0 else []
    canonical = {
        "mode": request.mode,
        "message": normalize_text(request.message),
        "history": [[turn.role, normalize_text(turn.text)] for turn in recent],
    }
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f"analyze:{namespace}:{digest}"


class CachingAssistant:
    """Декоратор Assistant: отдаёт готовый ответ из кеша и сливает одновременные одинаковые запросы.

    Attributes:
        inner: Ассистент, который генерирует ответ при промахе.
        cache: Хранилище ответов.
        namespace: Версия окружения ответа (промпты, модель, база знаний).
        ttl_seconds: Время жизни записи в кеше.
        history_turns: Сколько последних реплик входит в ключ.
    """

    def __init__(
        self, inner: Assistant, cache: ResponseCache, namespace: str, ttl_seconds: int, history_turns: int
    ) -> None:
        """Собирает декоратор.

        Args:
            inner: Ассистент, который генерирует ответ при промахе.
            cache: Хранилище ответов.
            namespace: Версия окружения ответа.
            ttl_seconds: Время жизни записи в кеше.
            history_turns: Сколько последних реплик входит в ключ.
        """
        self.inner = inner
        self.cache = cache
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self.history_turns = history_turns
        self._inflight: dict[str, asyncio.Task[AnalyzeResponse]] = {}

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Возвращает ответ из кеша или генерирует новый.

        Args:
            request: Запрос на обработку обращения.

        Returns:
            Ответ; при попадании в кеш (в том числе слиянием с уже идущим запросом) ``cache_status="hit"``,
            расход токенов нулевой.

        Raises:
            LlmUnavailable: Модель недоступна (ошибки в кеш не попадают).
        """
        started = time.perf_counter()
        key = build_cache_key(request, self.namespace, self.history_turns)

        if request.refresh:
            logger.info("Кеш: пропущен по запросу обновления, ответ генерируется заново")
            return await self._generate_and_store(key, request)

        cached = await self.cache.get(key)
        if cached is not None:
            logger.info("Кеш: попадание, вызов модели пропущен")
            return self._as_hit(cached, started)

        pending = self._inflight.get(key)
        if pending is not None:
            logger.info("Кеш: запрос слит с уже идущим одинаковым")
            return self._as_hit(await asyncio.shield(pending), started)

        task = asyncio.ensure_future(self._generate_and_store(key, request))
        self._inflight[key] = task
        task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _generate_and_store(self, key: str, request: AnalyzeRequest) -> AnalyzeResponse:
        """Генерирует ответ и кладёт его в кеш.

        Args:
            key: Ключ кеша.
            request: Запрос на обработку обращения.

        Returns:
            Свежесгенерированный ответ.
        """
        response = await self.inner.analyze(request)
        await self.cache.set(key, response.model_copy(update={"suggestion_id": None}), self.ttl_seconds)
        return response

    @staticmethod
    def _as_hit(response: AnalyzeResponse, started: float) -> AnalyzeResponse:
        """Помечает ответ как отданный из кеша.

        Args:
            response: Закешированный или слитый ответ.
            started: Момент начала обработки (perf_counter) для расчёта задержки.

        Returns:
            Копия ответа с ``cache_status="hit"``, нулевыми токенами и фактической задержкой.
        """
        usage = Usage(tokens_in=0, tokens_out=0, latency_ms=int((time.perf_counter() - started) * 1000))
        return response.model_copy(update={"cache_status": "hit", "usage": usage, "suggestion_id": None})
