"""Порты: интерфейсы, от которых зависят сервисы. Реализации лежат в integrations/ и db/."""

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.generation import GenerationInput, LlmOutput
from app.domain.knowledge import Hit
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.schemas.stats import StatsResponse


@dataclass(frozen=True)
class WebhookEventRecord:
    """Сохранённое событие вебхука.

    Attributes:
        event_id: Идентификатор события от AmoCRM.
        payload: Тело события.
        status: received, processed, retry или failed.
    """

    event_id: str
    payload: dict[str, Any]
    status: str


@dataclass(frozen=True)
class RateDecision:
    """Решение ограничителя запросов.

    Attributes:
        allowed: Запрос укладывается в лимит.
        retry_after: Через сколько секунд окно лимита сбросится (для заголовка Retry-After).
    """

    allowed: bool
    retry_after: int


class Assistant(Protocol):
    """Сценарий «обращение клиента -> ответ и подсказка»; декораторы (кеш, запись) реализуют тот же интерфейс."""

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Готовит ответ клиенту и подсказку по допродаже.

        Args:
            request: Сообщение клиента, история диалога и режим.

        Returns:
            Ответ клиенту, подсказка менеджеру и служебные данные.
        """
        ...


class Retriever(Protocol):
    """Поиск по базе знаний."""

    def search_many(self, queries: list[str], top_k: int = 5) -> list[Hit]:
        """Ищет записи, релевантные набору запросов.

        Args:
            queries: Поисковые запросы (подвопросы обращения).
            top_k: Сколько записей вернуть.

        Returns:
            Записи по убыванию релевантности.
        """
        ...


class Generator(Protocol):
    """Генератор структурированных ответов (LLM или офлайн-шаблон)."""

    model_name: str
    mode: str

    async def generate(self, data: GenerationInput) -> LlmOutput:
        """Генерирует структурированный ответ.

        Args:
            data: Промпты и найденные записи.

        Returns:
            Разобранный результат и расход токенов.

        Raises:
            LlmUnavailable: Модель недоступна или ответ не удалось разобрать.
        """
        ...


class SuggestionStore(Protocol):
    """Хранилище выданных подсказок."""

    async def save(self, lead_id: str | None, client_message: str, response: AnalyzeResponse) -> int | None:
        """Сохраняет подсказку.

        Args:
            lead_id: Идентификатор сделки.
            client_message: Сообщение клиента.
            response: Готовый ответ.

        Returns:
            Идентификатор записи или None, если сохранить не удалось.
        """
        ...


class ResponseCache(Protocol):
    """Кеш готовых ответов."""

    async def get(self, key: str) -> AnalyzeResponse | None:
        """Возвращает закешированный ответ.

        Args:
            key: Ключ кеша.

        Returns:
            Ответ или None, если его нет (или кеш недоступен).
        """
        ...

    async def set(self, key: str, response: AnalyzeResponse, ttl_seconds: int) -> None:
        """Кладёт ответ в кеш; недоступность кеша не должна ломать запрос.

        Args:
            key: Ключ кеша.
            response: Ответ для сохранения.
            ttl_seconds: Время жизни записи.
        """
        ...


class CrmClient(Protocol):
    """Клиент CRM, куда возвращается подсказка для менеджера."""

    async def add_note(self, lead_id: str, text: str) -> None:
        """Добавляет заметку в сделку.

        Args:
            lead_id: Идентификатор сделки.
            text: Текст заметки.
        """
        ...


class JobQueue(Protocol):
    """Очередь фоновых задач."""

    async def enqueue_webhook(self, event_id: str) -> None:
        """Ставит обработку события вебхука в очередь.

        Args:
            event_id: Идентификатор события.

        Raises:
            QueueUnavailable: Очередь недоступна.
        """
        ...


class WebhookEventStore(Protocol):
    """Хранилище событий вебхука (идемпотентность и статусы обработки)."""

    async def create(self, event_id: str, payload: dict[str, Any]) -> bool:
        """Сохраняет событие, если его ещё не было.

        Args:
            event_id: Идентификатор события.
            payload: Тело события.

        Returns:
            True, если событие новое; False, если такое уже принималось.
        """
        ...

    async def get(self, event_id: str) -> WebhookEventRecord | None:
        """Возвращает событие.

        Args:
            event_id: Идентификатор события.

        Returns:
            Событие или None.
        """
        ...

    async def set_status(self, event_id: str, status: str, error: str | None = None) -> None:
        """Обновляет статус обработки.

        Args:
            event_id: Идентификатор события.
            status: Новый статус.
            error: Текст ошибки, если есть.
        """
        ...

    async def delete(self, event_id: str) -> None:
        """Удаляет событие, чтобы повторная доставка была принята заново.

        Args:
            event_id: Идентификатор события.
        """
        ...


class RateLimiter(Protocol):
    """Ограничитель запросов (счётчик с фиксированным окном)."""

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        """Учитывает одно обращение и решает, укладывается ли оно в лимит.

        Args:
            key: Ключ счётчика (клиент, сутки и т. п.).
            limit: Максимум обращений за окно.
            window_seconds: Длина окна; отсчёт начинается с первого обращения.

        Returns:
            Решение. Недоступность хранилища не должна блокировать работу: тогда обращение разрешается.
        """
        ...


class FeedbackStore(Protocol):
    """Хранилище оценок менеджеров."""

    async def save(self, suggestion_id: int, rating: int, comment: str | None, manager_id: str | None) -> int:
        """Сохраняет оценку; повторная оценка того же менеджера обновляет прежнюю.

        Args:
            suggestion_id: Оцениваемая подсказка.
            rating: 1 или -1.
            comment: Комментарий менеджера.
            manager_id: Идентификатор менеджера.

        Returns:
            Идентификатор оценки.

        Raises:
            SuggestionNotFound: Подсказки с таким идентификатором нет.
        """
        ...


class StatsProvider(Protocol):
    """Источник сводной статистики."""

    async def today(self) -> StatsResponse:
        """Считает статистику за текущие сутки (UTC).

        Returns:
            Сводка по подсказкам, токенам, кешу и оценкам.
        """
        ...
