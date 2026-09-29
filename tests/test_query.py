from app.domain.query import build_search_queries, split_questions
from app.schemas.analyze import DialogTurn

COMPOUND = "Здравствуйте! Сколько стоит цеолит Макс и есть ли доставка в Новосибирск?"


def test_split_questions_separates_compound_message() -> None:
    parts = split_questions(COMPOUND)

    assert parts == ["Сколько стоит цеолит Макс", "есть ли доставка в Новосибирск"]


def test_split_questions_drops_greeting() -> None:
    assert split_questions("Здравствуйте!") == []


def test_build_search_queries_adds_whole_message_to_parts() -> None:
    queries = build_search_queries(COMPOUND, [])

    assert queries == ["Сколько стоит цеолит Макс", "есть ли доставка в Новосибирск", COMPOUND]


def test_comma_before_question_word_splits_purchase_and_payment() -> None:
    history = [DialogTurn(role="client", text="Что у вас есть для общего очищения?")]

    queries = build_search_queries("Беру набор Детокс, как оплатить?", history)

    assert queries[:3] == [
        "Беру набор Детокс",
        "как оплатить",
        "Беру набор Детокс, как оплатить?",
    ]
    assert len(queries) == 4 and queries[3].startswith("Что у вас есть для общего очищения?")


def test_build_search_queries_single_question_is_one_query() -> None:
    message = "Расскажите, пожалуйста, про состав минерального комплекса"

    assert build_search_queries(message, []) == [message]


def test_short_followup_is_enriched_with_previous_client_turn() -> None:
    history = [
        DialogTurn(role="client", text="Интересует цеолит Стандарт"),
        DialogTurn(role="manager", text="Да, конечно"),
    ]

    assert build_search_queries("а цена?", history) == ["Интересует цеолит Стандарт а цена?"]


def test_regular_short_message_keeps_own_query_and_enriched_one() -> None:
    history = [DialogTurn(role="client", text="Интересует цеолит Стандарт")]

    queries = build_search_queries("Как быстро привезёте?", history)

    assert queries == ["Как быстро привезёте?", "Интересует цеолит Стандарт Как быстро привезёте?"]
