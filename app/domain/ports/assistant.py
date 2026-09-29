"""Порты ассистента: сценарий ответа, поиск по базе знаний, генератор и кеш готовых ответов."""

from typing import Protocol

from app.domain.generation import GenerationInput, LlmOutput
from app.domain.knowledge import Hit
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse


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
