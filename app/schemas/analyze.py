"""Схемы запросов и ответов HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field

PurchaseIntent = Literal["none", "interest", "ready_to_buy"]
CacheStatus = Literal["hit", "miss"]


class DialogTurn(BaseModel):
    """Одна реплика диалога в окне AmoCRM.

    Attributes:
        role: Автор реплики: клиент или менеджер.
        text: Текст реплики.
    """

    role: Literal["client", "manager"]
    text: str = Field(min_length=1, max_length=2000)


class AnalyzeRequest(BaseModel):
    """Обращение клиента и контекст диалога.

    Attributes:
        message: Новое сообщение клиента.
        history: Предыдущие реплики от старых к новым.
        lead_id: Идентификатор сделки в AmoCRM (необязателен).
        mode: ``rag`` — ответ по базе знаний; ``no_rag`` — демонстрационный режим без базы (для сравнения).
        refresh: Не брать ответ из кеша, а сгенерировать заново (кнопка «Обновить подсказку»); новый ответ заменяет кеш.
    """

    message: str = Field(min_length=1, max_length=2000)
    history: list[DialogTurn] = Field(default_factory=list, max_length=20)
    lead_id: str | None = Field(default=None, max_length=100)
    mode: Literal["rag", "no_rag"] = "rag"
    refresh: bool = False


class SourceRef(BaseModel):
    """Запись базы знаний, найденная по обращению.

    Attributes:
        entry_id: Идентификатор записи.
        title: Заголовок записи.
        category: Категория записи.
        source_url: Страница сайта, откуда взята запись.
        dense_score: Косинусная близость или None, если запись найдена только текстовым поиском.
        fused_score: Итоговая оценка гибридного поиска.
        used: Ответ построен на этой записи.
    """

    entry_id: str
    title: str
    category: str
    source_url: str
    dense_score: float | None
    fused_score: float
    used: bool


class Usage(BaseModel):
    """Расход ресурсов на один запрос.

    Attributes:
        tokens_in: Токены запроса к модели.
        tokens_out: Токены ответа модели.
        latency_ms: Полное время обработки запроса.
    """

    tokens_in: int
    tokens_out: int
    latency_ms: int


class AnalyzeResponse(BaseModel):
    """Два блока для менеджера и служебные данные.

    Attributes:
        suggestion_id: Идентификатор сохранённой подсказки (None, если сохранить не удалось).
        reply: Ответ клиенту.
        upsell_hint: Подсказка по допродаже (только для менеджера).
        priority: Клиент готов к покупке: подсказку стоит показать первой.
        purchase_intent: Оценка намерения купить.
        needs_escalation: Нужен менеджер или врач.
        analysis: Рассуждение модели (для отладки).
        sources: Найденные записи базы знаний.
        warnings: Замечания проверок (числа без опоры на базу и т. п.).
        mode: Режим генерации: rag, no_rag или offline.
        model: Модель, сгенерировавшая ответ.
        prompt_version: Версия набора промптов.
        usage: Расход токенов и время.
        cache_status: ``hit`` — ответ отдан из кеша без обращения к модели; ``miss`` — сгенерирован заново.
    """

    suggestion_id: int | None
    reply: str
    upsell_hint: str
    priority: bool
    purchase_intent: PurchaseIntent
    needs_escalation: bool
    analysis: str
    sources: list[SourceRef]
    warnings: list[str]
    mode: Literal["rag", "no_rag", "offline"]
    model: str
    prompt_version: str
    usage: Usage
    cache_status: CacheStatus = "miss"
