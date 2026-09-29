"""Состояние языковой модели: чем закончился последний вызов (для шапки консоли менеджера)."""

import json
import logging
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.schemas.stats import ModelAvailability, ModelStatus

logger = logging.getLogger(__name__)

HEALTH_KEY = "llm:health"
SELECTED_KEY = "llm:model"
MODELS_KEY = "llm:models"
HEALTH_TTL_SECONDS = 86_400
FAILURE_STATES = {"rate_limit", "budget", "unavailable"}


class LlmHealth:
    """Запоминает исход последнего свежего вызова модели; общий для API и worker'а (Redis), без Redis — в памяти.

    Ответы из кеша модель не вызывают и состояние не меняют. Ошибки Redis состояние не ломают: оно остаётся в памяти
    процесса.

    Attributes:
        model: Основная модель.
        fallback_model: Запасная модель.
        mode: ``llm`` или ``offline`` (нет ключа провайдера).
        prompt_version: Версия набора промптов.
        models: Модели, между которыми можно выбирать.
        redis: Клиент Redis или None.
    """

    def __init__(
        self,
        model: str = "",
        fallback_model: str | None = None,
        mode: str = "llm",
        prompt_version: str = "",
        redis: Redis | None = None,
        models: list[str] | None = None,
    ) -> None:
        """Собирает хранилище состояния.

        Args:
            model: Основная модель.
            fallback_model: Запасная модель.
            mode: ``llm`` или ``offline``.
            prompt_version: Версия набора промптов.
            redis: Клиент Redis (None — только память процесса).
            models: Модели, между которыми можно выбирать (по умолчанию — основная и запасная).
        """
        self.model = model
        self.fallback_model = fallback_model
        self.mode = mode
        self.prompt_version = prompt_version
        self.redis = redis
        self.models = models or [m for m in (model, fallback_model) if m]
        self._local: dict[str, str] = {}
        self._selected: str | None = None
        self._per_model: dict[str, dict[str, str]] = {}

    async def _write(self, fields: dict[str, str]) -> None:
        """Сохраняет поля состояния в памяти и в Redis.

        Args:
            fields: Поля для записи.
        """
        self._local.update(fields)
        if self.redis is None:
            return
        try:
            await self.redis.hset(HEALTH_KEY, mapping=fields)
            await self.redis.expire(HEALTH_KEY, HEALTH_TTL_SECONDS)
        except RedisError:
            logger.warning("Redis недоступен: состояние модели хранится только в памяти процесса")

    async def _read(self) -> dict[str, str]:
        """Читает состояние из Redis, а при сбое — из памяти.

        Returns:
            Поля состояния.
        """
        if self.redis is not None:
            try:
                stored = await self.redis.hgetall(HEALTH_KEY)
                if stored:
                    return dict(stored)
            except RedisError:
                logger.warning("Redis недоступен: состояние модели читается из памяти процесса")
        return dict(self._local)

    async def record_ok(self, model: str) -> None:
        """Отмечает успешный свежий вызов модели.

        Args:
            model: Модель, давшая ответ.
        """
        await self._write({"state": "ok", "last_model": model, "at": datetime.now(UTC).isoformat()})

    async def record_failure(self, state: str) -> None:
        """Отмечает отказ модели.

        Args:
            state: ``rate_limit``, ``budget`` или ``unavailable``.
        """
        state = state if state in FAILURE_STATES else "unavailable"
        await self._write({"state": state, "at": datetime.now(UTC).isoformat()})

    async def record_model(self, model: str, state: str, retry_after: int | None = None) -> None:
        """Запоминает исход вызова конкретной модели.

        Args:
            model: Идентификатор модели.
            state: ``ok``, ``rate_limit``, ``unavailable`` или ``bad_format``.
            retry_after: Через сколько секунд освободится лимит, если известно.
        """
        now = datetime.now(UTC)
        record = {
            "state": state,
            "at": now.isoformat(),
            "retry_until": (now + timedelta(seconds=retry_after)).isoformat() if retry_after else "",
        }
        self._per_model[model] = record
        if self.redis is None:
            return
        try:
            await self.redis.hset(MODELS_KEY, model, json.dumps(record))
            await self.redis.expire(MODELS_KEY, HEALTH_TTL_SECONDS)
        except RedisError:
            logger.warning("Redis недоступен: состояние моделей хранится только в памяти процесса")

    async def _read_models(self) -> dict[str, dict[str, str]]:
        """Читает состояния моделей из Redis, а при сбое — из памяти.

        Returns:
            Состояние по названию модели.
        """
        if self.redis is not None:
            try:
                stored = await self.redis.hgetall(MODELS_KEY)
                if stored:
                    return {name: json.loads(value) for name, value in stored.items()}
            except (RedisError, ValueError):
                logger.warning("Redis недоступен: состояния моделей читаются из памяти процесса")
        return dict(self._per_model)

    async def get_selected(self) -> str | None:
        """Возвращает модель, выбранную менеджером.

        Returns:
            Идентификатор модели или None, если выбран автоматический порядок (в том числе при сбое Redis).
        """
        if self.redis is not None:
            try:
                value = await self.redis.get(SELECTED_KEY)
                self._selected = value or None
            except RedisError:
                logger.warning("Redis недоступен: выбор модели берётся из памяти процесса")
        return self._selected if self._selected in self.models else None

    async def set_selected(self, model: str | None) -> None:
        """Запоминает выбранную модель и сбрасывает прежний отказ: новая модель ещё не пробовалась.

        Args:
            model: Идентификатор модели или None для автоматического порядка.

        Raises:
            ValueError: Такой модели нет в списке.
        """
        if model is not None and model not in self.models:
            raise ValueError(model)
        self._selected = model
        if self.redis is not None:
            if model is None:
                await self.redis.delete(SELECTED_KEY)
            else:
                await self.redis.set(SELECTED_KEY, model)
        await self._write({"state": "ok", "last_model": "", "at": datetime.now(UTC).isoformat()})

    async def snapshot(self) -> ModelStatus:
        """Возвращает текущее состояние модели.

        Returns:
            Состояние для шапки консоли: без ключа провайдера — ``offline``, иначе исход последнего вызова.
        """
        stored = await self._read()
        state = "offline" if self.mode == "offline" else stored.get("state", "ok")
        return ModelStatus(
            state=state,
            model=self.model,
            last_model=stored.get("last_model") or None,
            fallback_model=self.fallback_model,
            prompt_version=self.prompt_version,
            checked_at=stored.get("at") or None,
            models=self.models,
            selected=await self.get_selected(),
            per_model=await self._availability(),
        )

    async def _availability(self) -> dict[str, ModelAvailability]:
        """Собирает состояние каждой модели по её последнему вызову.

        Returns:
            Состояние по названию модели; лимит с прошедшим сроком помечается ``limit_expired``.
        """
        now = datetime.now(UTC)
        records = await self._read_models()
        result: dict[str, ModelAvailability] = {}
        for model in self.models:
            record = records.get(model)
            if not record:
                result[model] = ModelAvailability(state="unknown")
                continue
            state, retry_in = record.get("state", "unknown"), None
            if state == "rate_limit":
                until = datetime.fromisoformat(record["retry_until"]) if record.get("retry_until") else None
                if until is not None and until > now:
                    retry_in = int((until - now).total_seconds()) + 1
                else:
                    state = "limit_expired"
            result[model] = ModelAvailability(state=state, retry_in=retry_in, checked_at=record.get("at") or None)
        return result
