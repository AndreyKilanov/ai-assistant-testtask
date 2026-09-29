from app.domain.guardrails import (
    DISCLAIMER,
    is_health_related,
    is_high_risk_health,
    unsupported_numbers,
    with_health_disclaimer,
)


def test_unsupported_numbers_flags_invented_price() -> None:
    supporting = "Цена: 7 790 ₽, с промокодом 6 590 ₽. Упаковка 120 пакетиков."

    assert unsupported_numbers("Стоит 7 790 ₽ или 5 000 ₽, доставка 2 дня", supporting) == ["5 000"]


def test_unsupported_numbers_ignores_short_numbers() -> None:
    assert unsupported_numbers("Пришлём 2 упаковки за 3 дня", "") == []


def test_is_health_related() -> None:
    assert is_health_related("А беременным можно?")
    assert is_health_related("У ребёнка аллергия")
    assert not is_health_related("Сколько стоит цеолит Макс и есть ли доставка")
    assert not is_health_related("Хочу набор Детокс")


def test_disclaimer_added_for_health_topic() -> None:
    reply = with_health_disclaimer("Производитель не называет это противопоказанием.", True, "Можно беременным?")

    assert reply.endswith(DISCLAIMER)


def test_disclaimer_skipped_for_price_question() -> None:
    reply = "Цеолит Макс стоит 7 790 ₽."

    assert with_health_disclaimer(reply, True, "Сколько стоит цеолит Макс?") == reply


def test_disclaimer_skipped_when_doctor_already_mentioned() -> None:
    reply = "При беременности лучше посоветоваться с врачом."

    assert with_health_disclaimer(reply, True, "Можно беременным?") == reply


def test_disclaimer_skipped_when_records_not_sensitive() -> None:
    assert with_health_disclaimer("Доставка СДЭК.", False, "А для детей?") == "Доставка СДЭК."


def test_high_risk_topics() -> None:
    assert is_high_risk_health("А беременным можно? Жена ждёт ребёнка")
    assert is_high_risk_health("Я принимаю лекарства от давления")
    assert not is_high_risk_health("Хочу что-нибудь от прыщей и набор Детокс")


def test_unsupported_evaluations_flags_invented_comparison() -> None:
    from app.domain.guardrails import unsupported_evaluations

    reply = "Цеолит Макс по цене за упаковку выходит выгоднее, чем наборы. Это самый популярный вариант."
    supporting = "Цеолит Макс — 120 пакетиков. Цена: 7 790 ₽. А цеолит Макс дороже?"

    assert unsupported_evaluations(reply, supporting) == ["выгоднее", "самый", "популярный"]


def test_unsupported_evaluations_ignores_adverb_luchshe_but_flags_adjective() -> None:
    from app.domain.guardrails import unsupported_evaluations

    assert unsupported_evaluations("Я подскажу, с чего лучше начать.", "") == []
    assert unsupported_evaluations("Это лучший вариант.", "") == ["лучший"]


def test_unsupported_evaluations_allows_words_present_in_data() -> None:
    from app.domain.guardrails import unsupported_evaluations

    supporting = "Самая крупная и выгодная упаковка; клиент спросил: это лучший вариант?"

    assert unsupported_evaluations("Это самая крупная упаковка, лучший вариант для курса", supporting) == []


def test_normalize_prices_unifies_format_with_nbsp() -> None:
    from app.domain.guardrails import normalize_prices

    text = "Макс — 7790 ₽, Стандарт 4 090₽, Мини 2\u00a0790 ₽, набор 11970 ₽."

    assert normalize_prices(text) == (
        "Макс — 7\u00a0790\u00a0₽, Стандарт 4\u00a0090\u00a0₽, Мини 2\u00a0790\u00a0₽, набор 11\u00a0970\u00a0₽."
    )


def test_normalize_prices_keeps_other_numbers_untouched() -> None:
    from app.domain.guardrails import normalize_prices

    assert normalize_prices("120 пакетиков по 2,5 г за 990 ₽") == "120 пакетиков по 2,5 г за 990\u00a0₽"


def test_callback_request_is_recognized_only_when_the_client_wants_to_be_called() -> None:
    from app.domain.guardrails import is_callback_request

    for text in ("пускай позвонят мне", "Позвоните мне пожалуйста", "хочу чтобы мне позвонили", "свяжитесь со мной"):
        assert is_callback_request(text), text
    for text in ("куда позвонить?", "можно позвонить вам?", "сколько стоит цеолит", "какой у вас номер телефона"):
        assert not is_callback_request(text), text


def test_foreign_urls_are_removed_but_known_pages_and_bare_domain_stay() -> None:
    from app.domain.guardrails import is_link_request, strip_foreign_urls

    known = {"https://o-complex.com/product/zeolite-max-67/"}

    assert strip_foreign_urls("Вот ссылка на страницу товара: https://o-complex.com/товар", known) == "Вот ссылка на страницу товара."
    assert strip_foreign_urls("Смотрите https://o-complex.com/product/zeolite-max-67/ .", known).count("zeolite-max-67") == 1
    assert strip_foreign_urls("Закажите на сайте o-complex.com, там удобно.", known) == "Закажите на сайте o-complex.com, там удобно."
    assert is_link_request("дай ссылку на товар") and is_link_request("где купить?") and not is_link_request("сколько стоит")
