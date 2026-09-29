"""Схема сводной статистики за сутки."""

from pydantic import BaseModel


class StatsResponse(BaseModel):
    """Статистика работы ассистента за текущие сутки (UTC).

    Attributes:
        date: Дата, за которую собрана статистика.
        requests_total: Все выданные подсказки.
        cache_hits: Подсказки, отданные из кеша без вызова модели.
        llm_calls: Подсказки, сгенерированные заново.
        cache_hit_ratio: Доля ответов из кеша.
        tokens_in: Токены запросов к модели.
        tokens_out: Токены ответов модели.
        avg_latency_llm_ms: Средняя задержка ответа, сгенерированного моделью.
        avg_latency_cache_ms: Средняя задержка ответа из кеша.
        daily_llm_limit: Дневной бюджет обращений к модели.
        feedback_positive: Положительные оценки менеджеров.
        feedback_negative: Отрицательные оценки менеджеров.
    """

    date: str
    requests_total: int
    cache_hits: int
    llm_calls: int
    cache_hit_ratio: float
    tokens_in: int
    tokens_out: int
    avg_latency_llm_ms: float | None
    avg_latency_cache_ms: float | None
    daily_llm_limit: int
    feedback_positive: int
    feedback_negative: int


class ModelAvailability(BaseModel):
    """Состояние одной модели по её последнему вызову.

    Attributes:
        state: ``ok`` — отвечала, ``rate_limit`` — лимит исчерпан, ``limit_expired`` — лимит мог освободиться,
            ``unavailable`` — недоступна, ``bad_format`` — ответила не по схеме, ``unknown`` — не вызывалась.
        retry_in: Через сколько секунд освободится лимит (только для ``rate_limit``).
        checked_at: Когда модель вызывалась в последний раз (ISO, UTC).
    """

    state: str
    retry_in: int | None = None
    checked_at: str | None = None


class ModelStatus(BaseModel):
    """Состояние языковой модели для шапки консоли менеджера.

    Attributes:
        state: ``ok`` — работает, ``rate_limit`` — исчерпан лимит провайдера, ``budget`` — исчерпан дневной бюджет
            обращений, ``unavailable`` — модель недоступна, ``offline`` — режим без ИИ.
        model: Основная модель.
        last_model: Модель, давшая последний свежий ответ (запасная, если основная не отвечала).
        fallback_model: Запасная модель.
        prompt_version: Версия набора промптов.
        checked_at: Когда состояние менялось в последний раз (ISO, UTC); None, если вызовов ещё не было.
        models: Модели, между которыми можно выбирать.
        selected: Модель, выбранная менеджером; None — автоматический порядок.
        per_model: Состояние каждой модели по её последнему вызову.
    """

    state: str
    model: str
    last_model: str | None
    fallback_model: str | None
    prompt_version: str
    checked_at: str | None
    models: list[str]
    selected: str | None
    per_model: dict[str, ModelAvailability] = {}


class ModelChoiceIn(BaseModel):
    """Выбор модели менеджером.

    Attributes:
        model: Идентификатор модели; None возвращает автоматический порядок.
    """

    model: str | None
