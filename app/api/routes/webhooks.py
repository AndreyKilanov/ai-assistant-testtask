"""Вебхук AmoCRM: быстрый приём события; тяжёлая обработка идёт в фоне."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_webhooks, verify_webhook_secret
from app.schemas.webhook import AmoWebhookPayload, WebhookAck
from app.services.webhooks import WebhookService

router = APIRouter(tags=["webhooks"])


@router.post(
    "/webhook/amocrm",
    response_model=WebhookAck,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_webhook_secret)],
)
async def amocrm_webhook(
    payload: AmoWebhookPayload, response: Response, webhooks: Annotated[WebhookService, Depends(get_webhooks)]
) -> WebhookAck:
    """Принимает событие «новое сообщение клиента»: повторная доставка возвращает 200 и ``duplicate``."""
    result = await webhooks.accept(payload)
    if result == "duplicate":
        response.status_code = status.HTTP_200_OK
    return WebhookAck(status=result, event_id=payload.event_id)
