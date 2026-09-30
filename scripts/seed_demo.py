"""Наполнение базы демо-диалогами: разные клиенты, статусы, способы связи и подсказки ИИ.

Запуск: ``python -m scripts.seed_demo`` (нужны Postgres и применённые миграции). Скрипт идемпотентен:
токены демо-диалогов детерминированы, поэтому повторный запуск заменяет прежние демо-данные,
а настоящие диалоги не трогает.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import ChatMessage, Conversation, Suggestion
from app.db.session import get_sessionmaker

DEMO_PREFIX = "demo-seed-"
KB = "https://o-complex.com"
KB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.json"


@dataclass
class Msg:
    """Сообщение демо-диалога.

    Attributes:
        sender: client, manager или system.
        text: Текст сообщения.
        ago_min: Сколько минут назад отправлено.
        auto: Ответил бот в режиме «менеджер ушёл».
        links: Кнопки-ссылки под сообщением.
    """

    sender: str
    text: str
    ago_min: int
    auto: bool = False
    links: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Hint:
    """Подсказка ИИ к последнему сообщению клиента.

    Attributes:
        reply: Предложенный ответ клиенту.
        upsell: Совет менеджеру по допродаже.
        intent: none, interest или ready_to_buy.
        escalation: Нужен менеджер или врач.
        sources: Идентификаторы использованных записей базы знаний (заголовок, категория и URL берутся из неё).
    """

    reply: str
    upsell: str
    intent: str = "none"
    escalation: bool = False
    sources: list[str] = field(default_factory=list)


@dataclass
class Demo:
    """Демо-диалог.

    Attributes:
        name: Имя клиента.
        status: new, in_progress, waiting_client, callback или closed.
        messages: Сообщения от старых к новым.
        hot: Клиент готов купить, менеджер ещё не ответил.
        contact: (способ, значение, удобное время, комментарий) для запроса связи.
        note: Внутренняя заметка менеджера.
        hint: Подсказка ИИ к последнему сообщению клиента.
    """

    name: str | None
    status: str
    messages: list[Msg]
    hot: bool = False
    contact: tuple[str, str, str, str] | None = None
    note: str = ""
    hint: Hint | None = None


DELIVERY = [{"title": "Доставка и оплата", "url": f"{KB}/dostavka-i-oplata/"}]
CATALOG = [{"title": "Каталог на сайте", "url": f"{KB}/katalog/"}]

DEMOS = [
    Demo(
        "Анна Соколова",
        "new",
        [
            Msg(
                "client",
                "Здравствуйте! Хочу заказать цеолит Макс, 120 пакетиков. Как оплатить и сколько идёт доставка?",
                6,
            ),
        ],
        hot=True,
        hint=Hint(
            "Здравствуйте, Анна! Цеолит Макс (120 пакетиков) можно оформить "
            "на сайте или через менеджера. Оплата и сроки "
            "доставки зависят от способа и региона — пришлите, пожалуйста, город, и я уточню детали.",
            "Клиент готов купить: предложите сразу оформить заказ и "
            "упомяните программу лояльности с бонусными баллами.",
            "ready_to_buy",
            sources=[
                "product-zeolite-max-67",
                "dostavka-i-oplata:delivery",
            ],
        ),
    ),
    Demo(
        "Дмитрий Орлов",
        "new",
        [
            Msg("client", "Добрый день. Чем отличается Цеолит Стандарт от Мини?", 41),
            Msg("client", "И что лучше брать для первого курса?", 39),
        ],
        hint=Hint(
            "Добрый день, Дмитрий! Цеолит Мини — 40 пакетиков, удобно попробовать; Стандарт — 60 пакетиков, хватает на "
            "полноценный курс. Для первого знакомства подойдёт Мини, для регулярного приёма — Стандарт.",
            "Расскажите про постоянный приём и предложите Стандарт как более выгодный по цене за пакетик.",
            "interest",
            sources=[
                "product-zeolite-standard-58",
                "product-zeolite-mini-3",
            ],
        ),
    ),
    Demo(
        "Мария Ким",
        "in_progress",
        [
            Msg("client", "Можно ли принимать цеолит при беременности?", 130),
            Msg(
                "manager",
                "Здравствуйте, Мария! По применению при беременности лучше "
                "сначала проконсультироваться с врачом. Я передам "
                "ваш вопрос эксперту.",
                122,
            ),
            Msg("client", "Хорошо, а кто может проконсультировать? У вас есть врач?", 25),
        ],
        note="Тема здоровья — не давать рекомендаций самим, направить к эксперту.",
        hint=Hint(
            "Мария, у нас есть консультация эксперта — оставьте удобный способ связи, и мы организуем звонок. "
            "Решение о приёме при беременности принимает врач.",
            "Не продавать сейчас: сначала консультация, затем — набор «Планирование беременности» по запросу.",
            "interest",
            escalation=True,
            sources=[
                "prichiny-vybrat-nas:pregnancy-use",
                "home:expert-consultation",
            ],
        ),
    ),
    Demo(
        "Игорь Петров",
        "in_progress",
        [
            Msg("client", "Здравствуйте, набор «Детокс» подойдёт при аллергии?", 300),
            Msg("manager", "Добрый день, Игорь! Уточните, пожалуйста, на что именно у вас аллергия?", 290),
            Msg("client", "На пыльцу, весной обостряется.", 280),
            Msg("manager", "Для сезонной аллергии есть отдельный набор «Антиаллергия». Отправить описание?", 270),
            Msg("client", "Да, скиньте, пожалуйста", 12),
        ],
        hint=Hint(
            "Конечно, Игорь! Набор «Антиаллергия» — подробное описание и состав на странице набора. Напомню, что при "
            "хронических состояниях стоит согласовать приём с врачом.",
            "После описания предложите вместе с набором минеральную бутылку.",
            "interest",
            sources=["product-antiallergiya-9"],
        ),
    ),
    Demo(
        "Екатерина Волкова",
        "waiting_client",
        [
            Msg("client", "Здравствуйте! Интересует набор «Чистая кожа», сколько стоит?", 1500),
            Msg(
                "manager",
                "Здравствуйте, Екатерина! Обычный набор — стандартная цена, "
                "интенсивный курс дороже, но рассчитан на более "
                "длительный приём. Какой вариант вам интересен?",
                1490,
                links=CATALOG,
            ),
        ],
        note="Ждём ответа по выбору курса. Напомнить завтра.",
    ),
    Demo(
        "Сергей Ветров",
        "waiting_client",
        [
            Msg("client", "Как оформить заказ, если я в Казахстане?", 2900),
            Msg(
                "manager",
                "Здравствуйте, Сергей! Укажите город — проверю варианты доставки в вашу страну.",
                2880,
                links=DELIVERY,
            ),
        ],
    ),
    Demo(
        "Ольга Никитина",
        "callback",
        [
            Msg("client", "Хочу стать оптовым партнёром, у меня магазин здорового питания. Что для этого нужно?", 75),
            Msg(
                "manager",
                "Здравствуйте, Ольга! Условия сотрудничества зависят от объёма, отправим маркетинговые материалы. Как "
                "удобнее связаться?",
                70,
            ),
            Msg("client", "Позвоните мне лучше, так проще обсудить.", 58),
        ],
        contact=("phone", "+7 916 555-01-42", "после 15:00", "Магазин в Москве, интересует опт от 50 наборов."),
        note="Оптовый лид. Подготовить условия партнёра и прайс.",
    ),
    Demo(
        "Александр Романов",
        "callback",
        [
            Msg("client", "Можно связаться со мной в Телеграме? Хочу обсудить набор для всей семьи.", 18),
        ],
        hot=True,
        contact=("telegram", "@a_romanov", "вечером", "Семья из четырёх человек."),
    ),
    Demo(
        "Татьяна Белова",
        "callback",
        [
            Msg("client", "Пришлите, пожалуйста, информацию на почту, там удобнее читать.", 200),
            Msg("manager", "Конечно, Татьяна! Оставьте адрес — отправим описание и цены.", 190),
            Msg("client", "tatiana.belova@example.com", 185),
        ],
        contact=("email", "tatiana.belova@example.com", "", "Нужны цены на наборы «Красота изнутри»."),
    ),
    Demo(
        "Наталья Фролова",
        "closed",
        [
            Msg("client", "Где найти инструкцию по применению набора «Антистресс»?", 4300),
            Msg(
                "manager",
                "Здравствуйте, Наталья! Инструкции к наборам доступны на "
                "сайте в разделе «Инструкции». Ссылку отправляю.",
                4290,
                links=[{"title": "Инструкции", "url": f"{KB}/instrukcii/"}],
            ),
            Msg("client", "Нашла, спасибо большое!", 4285),
        ],
        note="Вопрос решён, покупка оформлена самостоятельно.",
    ),
    Demo(
        "Павел Морозов",
        "closed",
        [
            Msg("client", "Купил зубную пасту мятную, а есть ли цитрусовая отдельно?", 8700),
            Msg(
                "manager",
                "Да, Павел, цитрусовая зубная паста есть в каталоге, продаётся отдельно.",
                8690,
                links=CATALOG,
            ),
            Msg("client", "Отлично, заказал обе", 8680),
            Msg("system", "Диалог закрыт менеджером.", 8679),
        ],
    ),
    Demo(
        None,
        "new",
        [
            Msg("client", "Привет! А у вас есть программа лояльности?", 3),
        ],
        hint=Hint(
            "Здравствуйте! Да, у нас есть программа лояльности с бонусными "
            "баллами за покупки. Расскажу, как их получить "
            "и потратить — какой продукт вас интересует?",
            "Уточните интерес клиента и предложите набор для первой покупки.",
            "none",
            sources=["home:loyalty-program"],
        ),
    ),
    Demo(
        "Виктория Зайцева",
        "in_progress",
        [
            Msg("client", "Волосы выпадают после родов, что посоветуете?", 600),
            Msg(
                "manager",
                "Здравствуйте, Виктория! Для восстановления после беременности у нас есть отдельный набор и курс "
                "«Крепкие волосы». Расскажу подробнее?",
                590,
            ),
            Msg("client", "Да, но сначала скажите про противопоказания, кормлю грудью.", 40),
        ],
        hot=False,
        note="Кормящая мама — обязательно упомянуть консультацию врача.",
        hint=Hint(
            "Виктория, при грудном вскармливании приём лучше согласовать с врачом. Противопоказания подробно описаны "
            "на сайте, а наш эксперт может проконсультировать дополнительно.",
            "После консультации предложите набор «Восстановление после беременности».",
            "interest",
            escalation=True,
            sources=[
                "prichiny-vybrat-nas:contraindications",
                "product-vosstanovlenie-posle-beremennosti-38",
            ],
        ),
    ),
    Demo(
        "Роман Гусев",
        "new",
        [
            Msg("client", "Ваша продукция сертифицирована? Хочу видеть документы.", 95),
        ],
        hint=Hint(
            "Здравствуйте, Роман! Продукция проходит сертификацию и контроль качества, документы можно посмотреть на "
            "странице сертификатов на сайте.",
            "Клиент сомневается: предложите отправить сертификаты и ответить на вопросы по производству.",
            "none",
            sources=["certificates:certificates"],
        ),
    ),
    Demo(
        "Юлия Андреева",
        "waiting_client",
        [
            Msg("client", "Сколько стоят сменные минералы для бутылки?", 480),
            Msg(
                "manager",
                "Юлия, добрый день! Цены на сменные минералы актуальны на странице каталога. Нужна доставка?",
                470,
                links=CATALOG,
            ),
        ],
    ),
]


def token_for(index: int) -> str:
    """Возвращает детерминированный токен демо-диалога.

    Args:
        index: Порядковый номер диалога в DEMOS.

    Returns:
        32 символа hex.
    """
    return hashlib.md5(f"{DEMO_PREFIX}{index}".encode()).hexdigest()  # noqa: S324 — не криптография, только идентификатор


def preview(text: str) -> str:
    """Обрезает текст до длины превью в списке входящих.

    Args:
        text: Текст сообщения.

    Returns:
        До 160 символов.
    """
    return text if len(text) <= 160 else text[:157] + "..."


async def seed() -> None:
    """Пересоздаёт демо-диалоги, сообщения и подсказки."""
    now = datetime.now(UTC)
    tokens = [token_for(i) for i in range(len(DEMOS))]
    settings = get_settings()
    entries = {entry["id"]: entry for entry in json.loads(KB_PATH.read_text(encoding="utf-8"))}

    async with get_sessionmaker()() as session:
        await session.execute(delete(Suggestion).where(Suggestion.lead_id.like(f"{DEMO_PREFIX}%")))
        await session.execute(delete(Conversation).where(Conversation.token.in_(tokens)))

        for index, demo in enumerate(DEMOS):
            first = demo.messages[0]
            last = demo.messages[-1]
            unread = 0
            for message in reversed(demo.messages):
                if message.sender != "client":
                    break
                unread += 1
            if demo.status in {"waiting_client", "closed"}:
                unread = 0

            requested = now - timedelta(minutes=demo.messages[-1].ago_min) if demo.contact else None
            conversation = Conversation(
                token=tokens[index],
                client_name=demo.name,
                channel="web",
                status=demo.status,
                contact_method=demo.contact[0] if demo.contact else None,
                contact_value=demo.contact[1] if demo.contact else None,
                preferred_time=(demo.contact[2] or None) if demo.contact else None,
                contact_comment=(demo.contact[3] or None) if demo.contact else None,
                contact_requested_at=requested,
                manager_note=demo.note,
                unread_by_manager=unread,
                last_message_preview=preview(last.text),
                last_message_at=now - timedelta(minutes=last.ago_min),
                hot=demo.hot,
                created_at=now - timedelta(minutes=first.ago_min),
                updated_at=now - timedelta(minutes=last.ago_min),
                closed_at=now - timedelta(minutes=last.ago_min) if demo.status == "closed" else None,
            )
            session.add(conversation)
            await session.flush()

            suggestion_id = None
            if demo.hint:
                hint = demo.hint
                client_text = next(m.text for m in reversed(demo.messages) if m.sender == "client")
                suggestion = Suggestion(
                    lead_id=f"{DEMO_PREFIX}{conversation.id}",
                    client_message=client_text,
                    reply=hint.reply,
                    upsell_hint=hint.upsell,
                    analysis="Демо-данные: подсказка подготовлена заранее.",
                    sources=[
                        {
                            "entry_id": entry_id,
                            "title": entries[entry_id]["title"],
                            "category": entries[entry_id]["category"],
                            "source_url": entries[entry_id]["source_url"],
                            "dense_score": 0.86,
                            "fused_score": 0.03,
                            "used": True,
                        }
                        for entry_id in hint.sources
                    ],
                    priority=hint.intent == "ready_to_buy",
                    purchase_intent=hint.intent,
                    needs_escalation=hint.escalation,
                    warnings=[],
                    mode="rag",
                    cache_hit=False,
                    model=settings.groq_model,
                    prompt_version=settings.prompt_version,
                    tokens_in=1200,
                    tokens_out=180,
                    latency_ms=950,
                    created_at=now - timedelta(minutes=last.ago_min),
                )
                session.add(suggestion)
                await session.flush()
                suggestion_id = suggestion.id

            last_client_index = max(i for i, m in enumerate(demo.messages) if m.sender == "client")
            for position, message in enumerate(demo.messages):
                is_target = suggestion_id is not None and position == last_client_index
                session.add(
                    ChatMessage(
                        conversation_id=conversation.id,
                        sender=message.sender,
                        text=message.text,
                        suggestion_id=suggestion_id if is_target else None,
                        suggestion_state="ready" if is_target else None,
                        auto=message.auto,
                        links=message.links,
                        created_at=now - timedelta(minutes=message.ago_min),
                    )
                )

        await session.commit()
    print(f"демо-диалогов создано: {len(DEMOS)}")


if __name__ == "__main__":
    asyncio.run(seed())
