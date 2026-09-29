"""Обработка вебхуков AmoCRM: приём с идемпотентностью и фоновая подготовка подсказки для менеджера."""

import logging
from typing import Literal

from app.core.errors import LlmUnavailable, QueueUnavailable
from app.core.metrics import WEBHOOK_EVENTS
from app.domain.ports import Assistant, CrmClient, JobQueue, WebhookEventStore
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.schemas.webhook import AmoWebhookPayload

logger = logging.getLogger(__name__)


def format_crm_note(response: AnalyzeResponse) -> str:
    """Оформляет подсказку как текст заметки в сделке.

    Args:
        response: Готовый ответ ассистента.

    Returns:
        Многострочный текст: приоритет, ответ клиенту, подсказка по допродаже, источники и предупреждения.
    """
    title = "ИИ-подсказка" + (" [ПРИОРИТЕТ: клиент готов купить]" if response.priority else "")
    lines = [title, f"Ответ клиенту:\n{response.reply}", f"Допродажа (только для менеджера):\n{response.upsell_hint}"]
    if response.needs_escalation:
        lines.append("Требуется участие менеджера или врача: в базе знаний нет полного ответа.")
    used = [source.title for source in response.sources if source.used]
    if used:
        lines.append("Источники: " + "; ".join(used))
    lines.extend(f"Внимание: {warning}" for warning in response.warnings)
    return "\n\n".join(lines)


class WebhookService:
    """Принимает события AmoCRM и обрабатывает их в фоне.

    Attributes:
        events: Хранилище событий (идемпотентность и статусы).
        queue: Очередь фоновых задач.
        assistant: Ассистент, готовящий ответ и подсказку.
        crm: Клиент CRM, куда возвращается подсказка.
    """

    def __init__(self, events: WebhookEventStore, queue: JobQueue, assistant: Assistant, crm: CrmClient) -> None:
        """Собирает сервис из зависимостей.

        Args:
            events: Хранилище событий.
            queue: Очередь фоновых задач.
            assistant: Ассистент.
            crm: Клиент CRM.
        """
        self.events = events
        self.queue = queue
        self.assistant = assistant
        self.crm = crm

    async def accept(self, payload: AmoWebhookPayload) -> Literal["accepted", "duplicate"]:
        """Принимает событие: отсекает повторную доставку и ставит обработку в очередь.

        AmoCRM доставляет вебхуки минимум один раз, поэтому дубли отсекаются по ``event_id``. Если очередь
        недоступна, событие удаляется, чтобы повторная доставка была принята заново.

        Args:
            payload: Событие вебхука.

        Returns:
            ``accepted`` — событие принято; ``duplicate`` — такое событие уже было.

        Raises:
            QueueUnavailable: Очередь недоступна.
        """
        if not await self.events.create(payload.event_id, payload.model_dump(mode="json")):
            WEBHOOK_EVENTS.labels("duplicate").inc()
            return "duplicate"
        try:
            await self.queue.enqueue_webhook(payload.event_id)
        except QueueUnavailable:
            await self.events.delete(payload.event_id)
            WEBHOOK_EVENTS.labels("queue_unavailable").inc()
            raise
        WEBHOOK_EVENTS.labels("accepted").inc()
        return "accepted"

    async def process(self, event_id: str, final_attempt: bool = True) -> None:
        """Готовит подсказку по событию и записывает её заметкой в сделку (вызывается worker'ом).

        Повторный запуск уже обработанного события ничего не делает, поэтому повторы очереди не дублируют заметки.

        Args:
            event_id: Идентификатор события.
            final_attempt: Последняя попытка: при недоступности модели событие получает статус ``failed``,
                иначе ``retry`` (и исключение перехватывает механизм повторов очереди).

        Raises:
            LlmUnavailable: Модель недоступна.
        """
        event = await self.events.get(event_id)
        if event is None or event.status == "processed":
            return
        payload = AmoWebhookPayload.model_validate(event.payload)
        request = AnalyzeRequest(message=payload.message, history=payload.history, lead_id=payload.lead_id)
        try:
            response = await self.assistant.analyze(request)
            await self.crm.add_note(payload.lead_id, format_crm_note(response))
        except LlmUnavailable as exc:
            await self.events.set_status(event_id, "failed" if final_attempt else "retry", str(exc))
            WEBHOOK_EVENTS.labels("failed" if final_attempt else "retry").inc()
            raise
        except Exception as exc:
            await self.events.set_status(event_id, "failed", repr(exc))
            WEBHOOK_EVENTS.labels("failed").inc()
            raise
        await self.events.set_status(event_id, "processed")
        WEBHOOK_EVENTS.labels("processed").inc()
        logger.info("Событие %s обработано: подсказка передана в CRM", event_id)
