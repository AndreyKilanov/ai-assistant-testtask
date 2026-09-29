"""Подготовка поисковых запросов из обращения клиента."""

import re

from app.schemas.analyze import DialogTurn

QUESTION_WORDS = "есть|как|какой|какая|какие|какое|сколько|можно|когда|где|куда|что|почему|подскажите"
SENTENCE_SPLIT = re.compile(r"[?!.;\n]+")
CONNECTOR_SPLIT = re.compile(
    rf"(?:\s+(?:и|а также|а ещё|а еще|ещё|еще)\s+|\s*,\s*)(?=(?:{QUESTION_WORDS})\b)",
    re.IGNORECASE,
)
MIN_PART_CHARS = 8
MIN_PART_WORDS = 2
FOLLOWUP_CHARS = 15
MAX_QUERIES = 5


def split_questions(message: str) -> list[str]:
    """Делит обращение на отдельные вопросы.

    Составное обращение («сколько стоит цеолит и есть ли доставка») размывает один поисковый запрос, поэтому
    режем по знакам препинания и по союзам или запятой перед вопросительными словами. Части из одного слова
    (приветствия) и слишком короткие отбрасываются.

    Args:
        message: Сообщение клиента.

    Returns:
        Список подвопросов; пустой, если разбить осмысленно не удалось.
    """
    parts: list[str] = []
    for sentence in SENTENCE_SPLIT.split(message):
        parts.extend(CONNECTOR_SPLIT.split(sentence))
    stripped = (part.strip() for part in parts)
    return [part for part in stripped if len(part) >= MIN_PART_CHARS and len(part.split()) >= MIN_PART_WORDS]


def build_search_queries(message: str, history: list[DialogTurn]) -> list[str]:
    """Формирует поисковые запросы по обращению и контексту диалога.

    Составное обращение даёт запрос на каждый подвопрос плюс запрос по сообщению целиком. Реплика-продолжение
    («а цена?») сама по себе бессмысленна и заменяется предыдущей репликой клиента вместе с ней; у обычной
    короткой реплики такой запрос добавляется, чтобы не потерять тему разговора.

    Args:
        message: Новое сообщение клиента.
        history: Предыдущие реплики.

    Returns:
        От одного до MAX_QUERIES запросов без повторов.
    """
    previous = next((turn.text for turn in reversed(history) if turn.role == "client"), "")
    enriched = f"{previous} {message}".strip()
    if len(message) < FOLLOWUP_CHARS:
        return [enriched]
    parts = split_questions(message)
    queries = [*(parts if len(parts) >= 2 else []), message]
    if previous:
        queries.append(enriched)
    return list(dict.fromkeys(queries))[:MAX_QUERIES]
