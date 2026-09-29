"""Запасной генератор без LLM: ответ из лучшей найденной записи базы знаний."""

from app.domain.generation import GenerationInput, LlmOutput, LlmResult


class OfflineGenerator:
    """Генератор без обращения к модели (реализует порт Generator).

    Используется, когда ключ Groq не задан, чтобы демонстрация не падала.

    Attributes:
        model_name: Метка модели в ответе API.
        mode: Метка режима в ответе API.
    """

    model_name = "offline-template"
    mode = "offline"

    async def generate(self, data: GenerationInput) -> LlmOutput:
        """Строит ответ по шаблону из первой записи.

        Args:
            data: Промпты и найденные записи (используются только записи).

        Returns:
            Результат без расхода токенов.
        """
        if not data.hits:
            result = LlmResult(
                analysis="В базе знаний ничего не найдено; генерация отключена (нет ключа LLM).",
                reply="Спасибо за обращение! Уточню детали и вернусь к вам с ответом.",
                upsell_hint="Задайте клиенту уточняющий вопрос: что именно ему нужно подобрать.",
                purchase_intent="none",
                needs_escalation=True,
                used_entry_ids=[],
            )
        else:
            best = data.hits[0]
            result = LlmResult(
                analysis=f"Офлайн-режим: выбрана лучшая запись «{best.title}».",
                reply=f"Здравствуйте! {best.answer}",
                upsell_hint=best.upsell or "Уточните потребности клиента и предложите подходящий набор.",
                purchase_intent="none",
                needs_escalation=False,
                used_entry_ids=[best.entry_id],
            )
        return LlmOutput(result=result, tokens_in=0, tokens_out=0, model=self.model_name)
