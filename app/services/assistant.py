"""Ядро сценария: поиск по базе знаний, вызов модели и детерминированные проверки ответа.

Сервис ничего не знает о кеше, БД и очередях: они подключаются декораторами (см. caching.py, recording.py).
"""

import asyncio
import time

from app.core.config import Settings
from app.domain.generation import GenerationInput
from app.domain.guardrails import (
    HIGH_RISK_UPSELL,
    is_high_risk_health,
    normalize_prices,
    strip_foreign_urls,
    unsupported_evaluations,
    unsupported_numbers,
    with_health_disclaimer,
)
from app.domain.knowledge import is_relevant
from app.domain.ports import Generator, Retriever
from app.domain.query import build_search_queries
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse, SourceRef, Usage
from app.services.links import site_link_urls
from app.services.prompting import build_user_message, format_dialog, format_knowledge, load_prompt

TOP_K = 5


class AssistantService:
    """Готовит для менеджера ответ клиенту и подсказку по допродаже.

    Attributes:
        retriever: Поиск по базе знаний.
        generator: Генератор ответов (Groq или офлайн).
        settings: Настройки приложения.
    """

    def __init__(self, retriever: Retriever, generator: Generator, settings: Settings) -> None:
        """Собирает сервис из зависимостей.

        Args:
            retriever: Поиск по базе знаний.
            generator: Генератор ответов.
            settings: Настройки приложения.
        """
        self.retriever = retriever
        self.generator = generator
        self.settings = settings

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Обрабатывает обращение клиента.

        Args:
            request: Сообщение клиента, история диалога и режим.

        Returns:
            Ответ клиенту, подсказка менеджеру, источники, предупреждения проверок и расход токенов.

        Raises:
            LlmUnavailable: Модель недоступна или вернула ответ неверного формата.
        """
        started = time.perf_counter()
        use_rag = request.mode == "rag"
        hits = []
        if use_rag:
            queries = build_search_queries(request.message, request.history)
            hits = await asyncio.to_thread(self.retriever.search_many, queries, TOP_K)
        context = hits if use_rag and is_relevant(hits, self.settings.rag_min_dense_score) else []
        dialog_text = " ".join([request.message, *(turn.text for turn in request.history if turn.role == "client")])
        high_risk = use_rag and is_high_risk_health(dialog_text)
        if high_risk:
            context = [hit for hit in context if hit.category != "kit"]

        # Записей нет (приветствие, болтовня, непонятное сообщение): отвечаем как консультант без базы знаний,
        # а не передаём менеджеру. Тема здоровья остаётся на основном промпте с его проверками.
        no_match = use_rag and not context and not high_risk
        if no_match:
            prompt_name = "analyze_system_no_match"
        else:
            prompt_name = "analyze_system" if use_rag else "analyze_system_no_rag"
        system = load_prompt(self.settings.prompt_version, prompt_name)
        user = build_user_message(request.message, request.history, None if no_match or not use_rag else context)
        output = await self.generator.generate(GenerationInput(system=system, user=user, hits=context))
        result = output.result

        context_ids = {hit.entry_id for hit in context}
        used_ids = [entry_id for entry_id in result.used_entry_ids if entry_id in context_ids]
        used_hits = [hit for hit in context if hit.entry_id in used_ids] or context[:1]
        reply = with_health_disclaimer(result.reply, any(hit.sensitive for hit in used_hits), request.message)

        allowed_urls = {hit.source_url for hit in hits} | site_link_urls()
        reply = strip_foreign_urls(normalize_prices(reply), allowed_urls)
        upsell_hint, warnings = strip_foreign_urls(normalize_prices(result.upsell_hint), allowed_urls), []
        if high_risk:
            upsell_hint = HIGH_RISK_UPSELL
            warnings.append("Тема здоровья повышенного риска: подсказка по допродаже заменена стандартной.")

        supporting = "\n".join(
            [request.message, format_dialog(request.history), format_knowledge(context) if context else ""]
        )
        unsupported = unsupported_numbers(f"{reply}\n{upsell_hint}", supporting)
        if unsupported:
            warnings.append(f"Числа без подтверждения в базе знаний: {', '.join(unsupported)}")
        # Только сама реплика модели: в подсказке для менеджера («лучше дождаться») и в дисклеймере («лучше
        # проконсультироваться») такие слова не являются утверждением о товаре.
        evaluations = unsupported_evaluations(normalize_prices(result.reply), supporting)
        if evaluations:
            warnings.append(
                f"В ответе клиенту есть оценки или сравнения, которых нет в базе знаний: {', '.join(evaluations)}. "
                "Уберите их или проверьте, что это правда."
            )

        mode = "no_rag" if not use_rag else ("offline" if self.generator.mode == "offline" else "rag")
        return AnalyzeResponse(
            suggestion_id=None,
            reply=reply,
            upsell_hint=upsell_hint,
            priority=result.purchase_intent == "ready_to_buy",
            purchase_intent=result.purchase_intent,
            needs_escalation=result.needs_escalation,
            analysis=result.analysis,
            sources=[
                SourceRef(
                    entry_id=hit.entry_id,
                    title=hit.title,
                    category=hit.category,
                    source_url=hit.source_url,
                    dense_score=hit.dense_score,
                    fused_score=hit.fused_score,
                    used=hit.entry_id in used_ids,
                )
                for hit in hits
            ],
            warnings=warnings,
            mode=mode,
            model=output.model,
            prompt_version=self.settings.prompt_version,
            usage=Usage(
                tokens_in=output.tokens_in,
                tokens_out=output.tokens_out,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
            cache_status="miss",
        )
