"""Сущности генерации ответа: структурированный ответ модели, вход и выход генератора."""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.domain.knowledge import Hit
from app.schemas.analyze import PurchaseIntent


class LlmResult(BaseModel):
    """Структурированный ответ модели. Поле analysis идёт первым: модель сначала рассуждает."""

    analysis: str = Field(description="Краткое рассуждение по шагам, 2-5 предложений на русском")
    reply: str = Field(description="Вежливый ответ клиенту на русском")
    upsell_hint: str = Field(description="Подсказка менеджеру по допродаже на русском")
    purchase_intent: PurchaseIntent
    needs_escalation: bool
    used_entry_ids: list[str] = Field(description="id записей базы знаний, на которых основан ответ")


@dataclass(frozen=True)
class GenerationInput:
    """Вход генератора.

    Attributes:
        system: Системный промпт.
        user: Сообщение пользователя с базой знаний, диалогом и обращением клиента.
        hits: Записи базы знаний, переданные модели (нужны офлайн-генератору).
    """

    system: str
    user: str
    hits: list[Hit]


@dataclass(frozen=True)
class LlmOutput:
    """Результат генерации.

    Attributes:
        result: Разобранный ответ модели.
        tokens_in: Токены запроса.
        tokens_out: Токены ответа.
        model: Название модели.
    """

    result: LlmResult
    tokens_in: int
    tokens_out: int
    model: str
