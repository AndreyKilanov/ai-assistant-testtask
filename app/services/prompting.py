"""Сборка промптов: загрузка версионируемых файлов и оформление контекста для модели."""

from functools import lru_cache
from pathlib import Path

from app.domain.knowledge import Hit
from app.schemas.analyze import DialogTurn

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
MAX_HISTORY_CHARS = 4000


def format_rub(amount: int) -> str:
    """Форматирует сумму в рублях с пробелом как разделителем тысяч.

    Args:
        amount: Сумма в рублях.

    Returns:
        Строка вида ``6 590 ₽``.
    """
    return f"{amount:,}".replace(",", " ") + " ₽"


@lru_cache
def load_prompt(version: str, name: str) -> str:
    """Читает промпт из каталога prompts/<версия>/.

    Args:
        version: Версия набора промптов, например ``v1``.
        name: Имя файла без расширения.

    Returns:
        Текст промпта.
    """
    return (PROMPTS_DIR / version / f"{name}.md").read_text(encoding="utf-8")


def format_knowledge(hits: list[Hit]) -> str:
    """Оформляет найденные записи для промпта.

    Args:
        hits: Записи базы знаний.

    Returns:
        Текст для тега ``<knowledge_base>``; при отсутствии записей — явная пометка об этом.
    """
    if not hits:
        return "(по этому обращению в базе знаний ничего не найдено)"
    blocks = []
    for hit in hits:
        caution = " | осторожно: тема здоровья" if hit.sensitive else ""
        upsell = f"\nПодсказка по допродаже: {hit.upsell}" if hit.upsell else ""
        promo = (
            f"\nЦена по промокоду: {format_rub(hit.promo_price_rub)} "
            "(упомяни не больше одного раза за диалог и только если клиент спрашивает о цене или скидках)"
            if hit.promo_price_rub
            else ""
        )
        blocks.append(f"[id: {hit.entry_id} | {hit.category}{caution}]\n{hit.title}\n{hit.answer}{promo}{upsell}")
    return "\n\n".join(blocks)


def format_dialog(history: list[DialogTurn]) -> str:
    """Оформляет историю диалога, оставляя самые свежие реплики в пределах лимита символов.

    Args:
        history: Реплики от старых к новым.

    Returns:
        Текст для тега ``<dialog>``.
    """
    lines: list[str] = []
    total = 0
    for turn in reversed(history):
        line = f"{'Клиент' if turn.role == 'client' else 'Менеджер'}: {turn.text}"
        total += len(line)
        if total > MAX_HISTORY_CHARS:
            break
        lines.append(line)
    return "\n".join(reversed(lines)) or "(диалог только начался)"


def build_user_message(message: str, history: list[DialogTurn], hits: list[Hit] | None) -> str:
    """Собирает сообщение пользователя для модели.

    Args:
        message: Новое сообщение клиента.
        history: Предыдущие реплики.
        hits: Найденные записи; None — режим без базы знаний, блок ``<knowledge_base>`` не добавляется.

    Returns:
        Текст с тегами <knowledge_base>, <dialog>, <client_message>.
    """
    parts = []
    if hits is not None:
        parts.append(f"<knowledge_base>\n{format_knowledge(hits)}\n</knowledge_base>")
    parts.append(f"<dialog>\n{format_dialog(history)}\n</dialog>")
    parts.append(f"<client_message>\n{message}\n</client_message>")
    return "\n\n".join(parts)
