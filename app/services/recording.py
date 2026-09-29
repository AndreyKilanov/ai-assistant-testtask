"""Запись выданных подсказок: декоратор Assistant, сохраняющий каждый ответ (в том числе из кеша)."""

from app.domain.ports import Assistant, SuggestionStore
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse


class RecordingAssistant:
    """Декоратор Assistant: сохраняет подсказку и проставляет ``suggestion_id``.

    Стоит снаружи кеша, поэтому каждая выданная менеджеру подсказка получает свой идентификатор: к нему потом
    привязывается оценка менеджера.

    Attributes:
        inner: Ассистент (обычно с кешем), который готовит ответ.
        store: Хранилище подсказок.
    """

    def __init__(self, inner: Assistant, store: SuggestionStore) -> None:
        """Собирает декоратор.

        Args:
            inner: Ассистент, который готовит ответ.
            store: Хранилище подсказок.
        """
        self.inner = inner
        self.store = store

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Готовит ответ и сохраняет его.

        Args:
            request: Запрос на обработку обращения.

        Returns:
            Ответ с идентификатором сохранённой подсказки (None, если сохранить не удалось).

        Raises:
            LlmUnavailable: Модель недоступна.
        """
        response = await self.inner.analyze(request)
        suggestion_id = await self.store.save(request.lead_id, request.message, response)
        return response.model_copy(update={"suggestion_id": suggestion_id})
