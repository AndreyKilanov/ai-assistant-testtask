"""Контракт вебхука AmoCRM.

Это упрощённый JSON-контракт нашего адаптера: реальный формат вебхуков AmoCRM (form-encoded, подпись чат-API)
приводится к нему на границе интеграции.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analyze import DialogTurn


class AmoWebhookPayload(BaseModel):
    """Событие «новое сообщение клиента в сделке».

    Attributes:
        event_id: Уникальный идентификатор события; по нему отсекаются повторные доставки.
        lead_id: Идентификатор сделки в AmoCRM.
        message: Текст сообщения клиента.
        history: Предыдущие реплики диалога от старых к новым.
    """

    event_id: str = Field(min_length=1, max_length=200, pattern=r"^[\w.:\-]+$")
    lead_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    history: list[DialogTurn] = Field(default_factory=list, max_length=20)


class WebhookAck(BaseModel):
    """Ответ на вебхук.

    Attributes:
        status: ``accepted`` — событие принято в обработку; ``duplicate`` — такое событие уже было.
        event_id: Идентификатор события из запроса.
    """

    status: Literal["accepted", "duplicate"]
    event_id: str
