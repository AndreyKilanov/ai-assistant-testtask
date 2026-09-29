"""Кнопки-ссылки на сайт под ответом бота: страницы товаров, справочник страниц сайта, каталог и доставка."""

import json
import logging
from functools import lru_cache
from pathlib import Path

from app.schemas.analyze import AnalyzeResponse

logger = logging.getLogger(__name__)

SITE_LINKS_PATH = Path(__file__).resolve().parents[2] / "data" / "site_links.json"

SITE = "https://o-complex.com/"
CATALOG_URL = f"{SITE}katalog/"
DELIVERY_URL = f"{SITE}dostavka-i-oplata/"
PRODUCT_CATEGORIES = {"product", "kit"}
DELIVERY_CATEGORIES = {"delivery", "payment"}
MAX_LINKS = 3
MAX_TITLE = 42


@lru_cache
def load_site_links() -> tuple[dict, ...]:
    """Читает справочник страниц сайта (``data/site_links.json``): оплата, каталог, контакты, сертификаты и т. д.

    Справочник — единственный источник ссылок, которые бот может показывать помимо страниц найденных записей; так адреса не
    приходится выдумывать. Записи с адресом не с сайта компании пропускаются.

    Returns:
        Записи ``{id, title, url, keywords}``; пустой кортеж, если файл не читается.
    """
    try:
        entries = json.loads(SITE_LINKS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Справочник ссылок %s не прочитан", SITE_LINKS_PATH)
        return ()
    return tuple(e for e in entries if isinstance(e, dict) and str(e.get("url", "")).startswith(SITE) and e.get("title"))


def site_link_urls() -> set[str]:
    """Возвращает адреса всех страниц из справочника.

    Returns:
        Множество адресов, которые бот вправе показывать.
    """
    return {entry["url"] for entry in load_site_links()}


def match_site_links(text: str) -> list[dict[str, str]]:
    """Подбирает страницы справочника по ключевым словам в сообщении клиента.

    Args:
        text: Сообщение клиента.

    Returns:
        Ссылки ``{title, url}``: сначала те, где совпало больше ключевых слов.
    """
    lowered = text.casefold()
    scored = []
    for order, entry in enumerate(load_site_links()):
        hits = sum(keyword.casefold() in lowered for keyword in entry.get("keywords", []))
        if hits:
            scored.append((-hits, order, {"title": entry["title"], "url": entry["url"]}))
    return [link for _, _, link in sorted(scored, key=lambda item: item[:2])]


def _short(title: str) -> str:
    """Укорачивает подпись кнопки.

    Args:
        title: Заголовок записи.

    Returns:
        Заголовок не длиннее ``MAX_TITLE`` символов.
    """
    title = " ".join(title.split())
    return title if len(title) <= MAX_TITLE else title[: MAX_TITLE - 1].rstrip() + "…"


def build_links(response: AnalyzeResponse, asked_for_link: bool = False, message: str = "") -> list[dict[str, str]]:
    """Собирает кнопки-ссылки по записям, на которых построен ответ.

    Страницы товаров и наборов, по которым отвечала модель; страница доставки и оплаты, если ответ про неё; каталог, когда
    клиент готов купить, а конкретной страницы товара нет. Ссылки берутся только из базы знаний и только на сайт компании.

    Args:
        response: Подсказка ИИ с источниками.
        asked_for_link: Клиент просил ссылку: каталог показывается, даже если конкретного товара нет.
        message: Сообщение клиента: по нему из справочника подбираются страницы (оплата, контакты, сертификаты и т. д.).

    Returns:
        До трёх ссылок ``{title, url}``.
    """
    hot = response.purchase_intent == "ready_to_buy"
    used = [source for source in response.sources if source.used and source.source_url.startswith(SITE)]
    links: list[dict[str, str]] = []

    def add(title: str, url: str) -> None:
        if url not in {link["url"] for link in links} and len(links) < MAX_LINKS:
            links.append({"title": title, "url": url})

    products = [s for s in used if s.category in PRODUCT_CATEGORIES and "/product/" in s.source_url]
    for source in products[:2]:
        add(f"Заказать: {_short(source.title)}" if hot else _short(source.title), source.source_url)
    for link in match_site_links(message):
        add(link["title"], link["url"])
    if any(s.category in DELIVERY_CATEGORIES for s in used):
        add("Доставка и оплата", DELIVERY_URL)
    if (hot or asked_for_link) and not products and CATALOG_URL not in {link["url"] for link in links}:
        add("Каталог и заказ на сайте" if hot else "Каталог на сайте", CATALOG_URL)
    return links
