import pytest
from pydantic import ValidationError

from app.domain.emoji import has_emoji, strip_emoji
from app.schemas.analyze import AnalyzeRequest
from app.schemas.chat import ClientMessageIn, ClientStartIn, ManagerMessageIn
from tests.fakes import MAX_HIT, make_result, make_service


@pytest.mark.parametrize(
    "text",
    [
        "Привет 😀",
        "Спасибо 🙏🏼",
        "Готово ✅",
        "Топ ⭐",
        "Любим ❤️",
        "🇷🇺",
        "1️⃣ вариант",
        "Здравствуйте :)",
        "ок ;-)",
        "класс =D",
        "супер )))",
    ],
)
def test_has_emoji_detects_emoji_and_smileys(text: str) -> None:
    assert has_emoji(text)


@pytest.mark.parametrize(
    "text",
    [
        "Цеолит Макс — 7 790 ₽, доставка СДЭК: 3–5 дней.",
        "Ссылка: https://o-complex.com/katalog/ и http://example.com",
        "Заказ принят (пункт 8) и оплачен (см. 12:30)",
        "Клавиши ⌘ и ⌥, стрелка → и №5",
        "Ответ:Dolce, Note:Pro",
        "",
    ],
)
def test_has_emoji_ignores_regular_text(text: str) -> None:
    assert not has_emoji(text)


def test_strip_emoji_cleans_spacing() -> None:
    assert (
        strip_emoji("Здравствуйте! 😊 Цеолит Макс :) стоит 7 790 ₽ 👍.") == "Здравствуйте! Цеолит Макс стоит 7 790 ₽."
    )
    assert strip_emoji("Строка 1 😀\nСтрока 2") == "Строка 1\nСтрока 2"


def test_strip_emoji_keeps_clean_text_untouched() -> None:
    text = "  Обычный текст  с пробелами.\n"

    assert strip_emoji(text) == text


@pytest.mark.parametrize(
    "schema, payload",
    [
        (ClientStartIn, {"text": "Здравствуйте 😊"}),
        (ClientMessageIn, {"text": "Спасибо :)"}),
        (ManagerMessageIn, {"text": "Отправили заказ 👍"}),
    ],
)
def test_chat_schemas_reject_emoji(schema: type, payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="Эмодзи и смайлики"):
        schema(**payload)


def test_chat_schemas_accept_plain_text() -> None:
    assert ClientMessageIn(text="Сколько стоит цеолит Макс?").text == "Сколько стоит цеолит Макс?"
    assert ManagerMessageIn(text="Добрый день!").text == "Добрый день!"
    assert ClientStartIn().text is None


async def test_model_reply_and_hint_are_stripped_of_emoji() -> None:
    result = make_result(reply="Здравствуйте! 😊 Цеолит Макс :) стоит 7 790 ₽.", upsell_hint="Предложите набор 🎁 )))")
    service, *_ = make_service([MAX_HIT], result)

    response = await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))

    assert response.reply == "Здравствуйте! Цеолит Макс стоит 7\u00a0790\u00a0₽."
    assert response.upsell_hint == "Предложите набор"
