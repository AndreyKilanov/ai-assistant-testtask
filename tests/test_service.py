import pytest

from app.core.config import Settings
from app.core.errors import LlmUnavailable
from app.domain.guardrails import DISCLAIMER, HIGH_RISK_UPSELL
from app.schemas.analyze import AnalyzeRequest, DialogTurn
from app.services.assistant import AssistantService
from app.services.prompting import load_prompt
from tests.fakes import (
    DELIVERY_HIT,
    FAR_HIT,
    KIT_HIT,
    MAX_HIT,
    FailingGenerator,
    FakeRetriever,
    make_result,
    make_service,
)


async def test_analyze_uses_rag_and_marks_used_sources() -> None:
    service, retriever, generator = make_service([MAX_HIT, DELIVERY_HIT], make_result())

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert response.mode == "rag" and response.cache_status == "miss"
    assert [(s.entry_id, s.used) for s in response.sources] == [
        (MAX_HIT.entry_id, True),
        (DELIVERY_HIT.entry_id, False),
    ]
    assert response.usage.tokens_in == 100 and response.warnings == []
    assert "<knowledge_base>" in generator.received.user and MAX_HIT.answer in generator.received.user
    assert retriever.calls == [["Сколько стоит цеолит Макс?"]]


async def test_price_question_gets_no_health_disclaimer() -> None:
    service, *_ = make_service([MAX_HIT], make_result())

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert DISCLAIMER not in response.reply


async def test_health_question_gets_disclaimer() -> None:
    result = make_result(reply="По заявлению производителя, беременность не названа противопоказанием.")
    service, *_ = make_service([MAX_HIT], result)

    response = await service.analyze(AnalyzeRequest(message="Можно беременным?"))

    assert response.reply.endswith(DISCLAIMER)


async def test_irrelevant_hits_are_not_passed_to_model() -> None:
    result = make_result(reply="Уточню и вернусь с ответом.", needs_escalation=True, used_entry_ids=[])
    service, _, generator = make_service([FAR_HIT], result)

    response = await service.analyze(AnalyzeRequest(message="Как настроить роутер?"))

    assert "<knowledge_base>" not in generator.received.user
    assert generator.received.system == load_prompt("v2", "analyze_system_no_match")
    assert generator.received.hits == []
    assert response.needs_escalation and not any(s.used for s in response.sources)


async def test_unknown_used_ids_from_model_are_dropped() -> None:
    service, *_ = make_service([MAX_HIT], make_result(used_entry_ids=["выдуманный-id"]))

    response = await service.analyze(AnalyzeRequest(message="Цена цеолита?"))

    assert not any(source.used for source in response.sources)


async def test_invented_price_produces_warning() -> None:
    service, *_ = make_service([MAX_HIT], make_result(reply="Цеолит Макс стоит 4 999 ₽."))

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert response.warnings == ["Числа без подтверждения в базе знаний: 4 999"]


async def test_ready_to_buy_sets_priority() -> None:
    service, *_ = make_service([MAX_HIT], make_result(purchase_intent="ready_to_buy"))

    response = await service.analyze(AnalyzeRequest(message="Беру, как оплатить?"))

    assert response.priority and response.purchase_intent == "ready_to_buy"


async def test_no_rag_mode_skips_retrieval() -> None:
    service, retriever, generator = make_service([MAX_HIT], make_result(used_entry_ids=[]))

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит?", mode="no_rag"))

    assert response.mode == "no_rag" and response.sources == []
    assert retriever.calls == [] and "<knowledge_base>" not in generator.received.user


async def test_offline_generator_is_labelled() -> None:
    service, *_ = make_service([MAX_HIT], make_result(), mode="offline")

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert response.mode == "offline"


async def test_history_is_passed_to_model() -> None:
    service, _, generator = make_service([MAX_HIT], make_result())
    history = [DialogTurn(role="manager", text="Предлагаю набор Детокс")]

    await service.analyze(AnalyzeRequest(message="А подешевле есть?", history=history))

    assert "Менеджер: Предлагаю набор Детокс" in generator.received.user


async def test_llm_failure_propagates() -> None:
    service = AssistantService(FakeRetriever([MAX_HIT]), FailingGenerator(), Settings())

    with pytest.raises(LlmUnavailable):
        await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))


async def test_high_risk_topic_replaces_upsell_hint() -> None:
    service, *_ = make_service([MAX_HIT], make_result(upsell_hint="Предложите набор «Планирование беременности»."))

    response = await service.analyze(AnalyzeRequest(message="А беременным можно? Жена ждёт ребёнка"))

    assert response.upsell_hint == HIGH_RISK_UPSELL
    assert any("повышенного риска" in warning for warning in response.warnings)


async def test_high_risk_history_also_replaces_upsell_hint() -> None:
    service, *_ = make_service([MAX_HIT], make_result())
    history = [DialogTurn(role="client", text="Я кормящая мама")]

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?", history=history))

    assert response.upsell_hint == HIGH_RISK_UPSELL


async def test_no_rag_mode_does_not_replace_upsell() -> None:
    service, *_ = make_service([MAX_HIT], make_result(used_entry_ids=[]))

    response = await service.analyze(AnalyzeRequest(message="Можно беременным?", mode="no_rag"))

    assert response.upsell_hint != HIGH_RISK_UPSELL


async def test_high_risk_topic_hides_kits_from_model() -> None:
    service, _, generator = make_service([KIT_HIT, MAX_HIT], make_result())

    await service.analyze(AnalyzeRequest(message="А беременным можно? Жена ждёт ребёнка"))

    assert KIT_HIT.entry_id not in generator.received.user
    assert MAX_HIT.entry_id in generator.received.user


async def test_regular_topic_keeps_kits_in_context() -> None:
    service, _, generator = make_service([KIT_HIT, MAX_HIT], make_result())

    await service.analyze(AnalyzeRequest(message="Что посоветуете для общего очищения организма?"))

    assert KIT_HIT.entry_id in generator.received.user


def test_knowledge_block_gives_promo_price_as_separate_line_with_usage_rule() -> None:
    from app.services.prompting import format_knowledge

    text = format_knowledge([MAX_HIT])

    assert "Цена: 7 790 ₽." in text and "с промокодом" not in text.split("Цена по промокоду")[0]
    assert "Цена по промокоду: 6 590 ₽" in text and "не больше одного раза за диалог" in text


def test_knowledge_block_has_no_promo_line_when_entry_has_none() -> None:
    from app.services.prompting import format_knowledge

    assert "промокоду" not in format_knowledge([DELIVERY_HIT])


def test_v2_prompt_forbids_service_words_and_repeated_promo_code() -> None:
    from app.services.prompting import load_prompt

    prompt = load_prompt("v2", "analyze_system")

    assert "не больше одного раза за весь диалог" in prompt
    assert "«база знаний»" in prompt and "Промокод, скидка и бонусные баллы допродажей не считаются" in prompt


def test_default_prompt_version_is_v2() -> None:
    assert Settings().prompt_version == "v2"


async def test_manager_disclaimer_in_history_does_not_trigger_high_risk() -> None:
    service, *_ = make_service([MAX_HIT], make_result())
    history = [
        DialogTurn(role="client", text="Расскажите про антиаллергический набор"),
        DialogTurn(role="manager", text=f"Набор для снижения аллергенов. {DISCLAIMER}"),
    ]

    response = await service.analyze(AnalyzeRequest(message="А сколько стоит цеолит Макс?", history=history))

    assert response.upsell_hint != HIGH_RISK_UPSELL


async def test_invented_comparison_produces_warning() -> None:
    result = make_result(reply="Цеолит Макс стоит 7 790 ₽, по цене за упаковку это выгоднее наборов.")
    service, *_ = make_service([MAX_HIT], result)

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert any(
        "оценки или сравнения, которых нет в базе знаний" in warning and "выгоднее" in warning
        for warning in response.warnings
    )


async def test_soft_words_in_upsell_hint_do_not_produce_evaluation_warning() -> None:
    result = make_result(upsell_hint="Допродажа сейчас не уместна, лучше дождаться выбора категории.")
    service, *_ = make_service([MAX_HIT], result)

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert not any("оценки или сравнения" in warning for warning in response.warnings)


async def test_prices_in_reply_and_upsell_are_normalized_without_new_warnings() -> None:
    result = make_result(
        reply="Цеолит Макс стоит 7790 ₽, по промокоду 6590₽.", upsell_hint="Мини за 2790 ₽ подойдёт для пробы."
    )
    service, *_ = make_service([MAX_HIT], result)

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert "7\u00a0790\u00a0₽" in response.reply and "6\u00a0590\u00a0₽" in response.reply
    assert "2\u00a0790\u00a0₽" in response.upsell_hint
    assert not any("Числа без подтверждения" in warning for warning in response.warnings if "2" not in warning)


async def test_health_topic_without_matches_stays_on_the_main_prompt() -> None:
    result = make_result(reply="Лучше посоветоваться с врачом.", needs_escalation=True, used_entry_ids=[])
    service, _, generator = make_service([FAR_HIT], result)

    await service.analyze(AnalyzeRequest(message="Можно ли беременным пить лекарства вместе с цеолитом?"))

    assert generator.received.system == load_prompt("v2", "analyze_system")


async def test_invented_links_are_stripped_from_reply() -> None:
    result = make_result(reply="Вот ссылка на страницу товара: https://o-complex.com/товар", used_entry_ids=[])
    service, *_ = make_service([MAX_HIT], result)

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert "http" not in response.reply and response.reply == "Вот ссылка на страницу товара."
