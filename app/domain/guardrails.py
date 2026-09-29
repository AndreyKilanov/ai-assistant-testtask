"""Детерминированные проверки ответа модели, не зависящие от промпта."""

import re

DISCLAIMER = (
    "Это справочная информация от производителя, а не медицинская рекомендация: "
    "по вопросам здоровья, беременности и приёма лекарств лучше проконсультироваться с врачом."
)
DOCTOR_WORDS = ("врач", "специалист", "медицинск")
HEALTH_RE = re.compile(
    r"\b(беремен|кормлен|кормящ|грудн|ребён|ребен|дет(?:и|ей|ям|ьми|ск)|аллерг|астм|болезн|болен|болит|лекарств|препарат|"
    r"лечени|лечит|диагноз|симптом|давлен|диабет|онколог|хронич|токсикоз|противопоказ|побочн|дозиров|таблетк)",
    re.IGNORECASE,
)
HIGH_RISK_RE = re.compile(
    r"\b(беремен|кормлен|кормящ|грудн|ребён|ребен|дет(?:и|ей|ям|ьми|ск)|лекарств|препарат|хронич|диагноз|онколог|диабет|"
    r"давлен|таблетк)",
    re.IGNORECASE,
)
HIGH_RISK_UPSELL = (
    "Тема здоровья повышенного риска (беременность, дети, лекарства, хронические болезни): не предлагайте товары "
    "«для здоровья» и наборы под состояния, пока клиент не получил рекомендацию врача. Допродажа сейчас не уместна."
)
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)\s?₽")
NBSP = "\u00a0"
NUMBER_RE = re.compile(r"\d[\d\s\xa0]*\d")
MIN_CHECKED_DIGITS = 3


def _digits(number: str) -> str:
    """Оставляет в числе только цифры.

    Args:
        number: Число с пробелами-разделителями, например ``6 590``.

    Returns:
        Строка из цифр, например ``6590``.
    """
    return re.sub(r"\D", "", number)


# «лучше» как наречие («лучше начать») не оценка товара, поэтому берутся только формы прилагательного «лучший»
EVALUATIVE_RE = re.compile(
    r"\b(выгодн\w*|самы[йеим]\w*|самая|самое|лучш(?:ий|ая|ее|ие|его|ей|ему|им|их|ую)|популярн\w*)", re.IGNORECASE
)
EVALUATIVE_STEM = 5


def unsupported_evaluations(text: str, supporting: str) -> list[str]:
    """Находит оценочные слова («выгоднее», «самый», «лучший», «популярный»), которых нет в данных.

    Модель склонна добавлять сравнения от себя («по цене за упаковку выгоднее наборов»). Слово считается
    подтверждённым, если его основа встречается в подтверждающем тексте (записи, сообщение клиента, диалог).

    Args:
        text: Проверяемый текст (ответ модели).
        supporting: Текст, где оценки считаются подтверждёнными.

    Returns:
        Оценочные слова без опоры, без повторов и в порядке появления.
    """
    known = supporting.casefold()
    found: list[str] = []
    for match in EVALUATIVE_RE.finditer(text):
        word = match.group(0).casefold()
        if word[:EVALUATIVE_STEM] not in known and word not in found:
            found.append(word)
    return found


def normalize_prices(text: str) -> str:
    """Приводит цены в рублях к единому виду ``7 790 ₽`` с неразрывными пробелами.

    Модель пишет то «7790 ₽», то «7 790₽»; единый формат убирает «прыгающий» вид чисел и не даёт сумме
    разорваться переносом строки между цифрами и знаком рубля.

    Args:
        text: Текст ответа или подсказки.

    Returns:
        Текст, где каждая сумма с ``₽`` записана с разделителем тысяч и неразрывным пробелом перед знаком.
    """

    def format_match(match: re.Match[str]) -> str:
        amount = int(re.sub(r"\D", "", match.group(1)))
        return f"{amount:,}".replace(",", NBSP) + f"{NBSP}₽"

    return PRICE_RE.sub(format_match, text)


def unsupported_numbers(text: str, supporting: str) -> list[str]:
    """Находит в тексте числа (цены, годы, телефоны), которых нет в подтверждающем тексте.

    Короткие числа (до двух цифр) не проверяются: «2 упаковки» или «3 пункта» безобидны.

    Args:
        text: Проверяемый текст (ответ модели).
        supporting: Текст, где числа считаются подтверждёнными (записи базы, сообщение клиента, диалог).

    Returns:
        Числа из ``text`` без опоры в ``supporting``, без повторов и в порядке появления.
    """
    known = {_digits(number) for number in NUMBER_RE.findall(supporting)}
    found: list[str] = []
    for raw in NUMBER_RE.findall(text):
        number = raw.strip().replace("\u00a0", " ")
        digits = _digits(number)
        if len(digits) >= MIN_CHECKED_DIGITS and digits not in known and number not in found:
            found.append(number)
    return found


def is_health_related(text: str) -> bool:
    """Определяет, затрагивает ли текст здоровье, лечение, беременность, детей или лекарства.

    Args:
        text: Проверяемый текст (сообщение клиента, ответ).

    Returns:
        True, если найден хотя бы один маркер медицинской темы.
    """
    return HEALTH_RE.search(text) is not None


def is_high_risk_health(text: str) -> bool:
    """Определяет темы повышенного риска: беременность, кормление, дети, лекарства, хронические болезни.

    Args:
        text: Проверяемый текст (сообщение клиента и история диалога).

    Returns:
        True, если найден хотя бы один маркер такой темы.
    """
    return HIGH_RISK_RE.search(text) is not None


def with_health_disclaimer(reply: str, sensitive: bool, message: str) -> str:
    """Добавляет к ответу оговорку про врача, когда разговор касается здоровья на основе записей о здоровье.

    Чисто товарные вопросы (цена, доставка) оговорку не получают: она там была бы неуместна.

    Args:
        reply: Ответ клиенту.
        sensitive: Среди использованных записей есть помеченные ``sensitive``.
        message: Сообщение клиента: оно тоже проверяется на медицинскую тему.

    Returns:
        Ответ без изменений, если оговорка не нужна или врач уже упомянут; иначе ответ с оговоркой.
    """
    if not sensitive or not is_health_related(f"{message} {reply}"):
        return reply
    if any(word in reply.lower() for word in DOCTOR_WORDS):
        return reply
    return f"{reply.rstrip()}\n\n{DISCLAIMER}"


CALLBACK_RE = re.compile(
    r"\b(мне|нам)\s+(?:по|пере)?звон"
    r"|\b(?:по|пере)?звон\w*\s+(мне|нам)\b"
    r"|\bперезвон"
    r"|\bсвя[жз]\w*\s+(со\s+мной|с\s+нами)"
    r"|\b(со\s+мной|с\s+нами)\s+свя[жз]"
    r"|\b(пусть|пускай|прошу|хочу|можно|попросите|нужно|надо)\b[^.?!]{0,40}\b(?:по|пере)?звон"
    r"|\b(пусть|пускай|прошу)\b[^.?!]{0,30}\bсвя[жз]\w*\s+(со\s+мной|с\s+нами)"
    r"|\b(заказать|закажите|обратный)\s+звон",
    re.IGNORECASE,
)
CALLBACK_FOLLOW_UP_RE = re.compile(
    r"\b(куда|когда|во сколько|на какой|по какому|откуда)\b[^.?!]{0,30}\b(?:по|пере)?звон"
    r"|\b(?:по|пере)?звон\w*\s+будете"
    r"|\bжду\b[^.?!]{0,20}звон",
    re.IGNORECASE,
)
CALL_THE_COMPANY_RE = re.compile(
    r"\b(куда|на какой номер|по какому номеру)\b[^.?!]{0,20}\bзвон|\b(?:по)?звонить\s+(вам|вас)", re.IGNORECASE
)


def is_callback_request(text: str, follow_up: bool = False) -> bool:
    """Определяет, просит ли клиент, чтобы ему позвонили или с ним связались.

    Вопросы вида «куда позвонить?» и «можно позвонить вам?» просьбой не считаются: клиент хочет позвонить сам.
    Если просьба уже была (``follow_up``), уточнения вроде «куда звонить будете?» относятся к ней же.

    Args:
        text: Сообщение клиента.
        follow_up: Диалог уже помечен как «просит связаться».

    Returns:
        True, если клиент просит перезвонить или связаться с ним.
    """
    if follow_up and CALLBACK_FOLLOW_UP_RE.search(text):
        return True
    return CALLBACK_RE.search(text) is not None and CALL_THE_COMPANY_RE.search(text) is None


URL_RE = re.compile(
    r"https?://[^\s<>()]+|(?<![\w@.-])(?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s<>()]*",
    re.IGNORECASE,
)
URL_TRAILING = ".,;:!?»\"'"
LINK_REQUEST_RE = re.compile(
    r"ссылк|\burl\b|на\s+сайт|страниц[ауы]\s+товар|где\s+(?:можно\s+)?(?:купить|заказать|посмотреть)"
    r"|как\s+(?:купить|заказать)|каталог",
    re.IGNORECASE,
)


def strip_foreign_urls(text: str, allowed: set[str]) -> str:
    """Убирает из текста ссылки, которых нет в базе знаний: модель не должна выдумывать адреса.

    Адрес без пути (``o-complex.com``) не считается ссылкой и остаётся. Ссылки на страницы даёт интерфейс кнопками.

    Args:
        text: Ответ или подсказка модели.
        allowed: Адреса страниц, которые встречаются в базе знаний.

    Returns:
        Текст без посторонних ссылок и без «висящих» знаков препинания на их месте.
    """

    def replace(match: re.Match[str]) -> str:
        url = match.group(0)
        core = url.rstrip(URL_TRAILING)
        return url if core in allowed else url[len(core) :]

    cleaned = URL_RE.sub(replace, text)
    if cleaned == text:
        return text
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([.,;!?])", r"\1", cleaned)
    return re.sub(r":\s*$", ".", cleaned)


def is_link_request(text: str) -> bool:
    """Определяет, просит ли клиент ссылку или страницу на сайте.

    Args:
        text: Сообщение клиента.

    Returns:
        True, если клиент просит ссылку, каталог или спрашивает, где купить и посмотреть.
    """
    return LINK_REQUEST_RE.search(text) is not None
