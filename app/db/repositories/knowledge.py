"""Версия базы знаний по таблице ``kb_documents``."""

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.db.models import KbDocument
from app.db.session import Sessionmaker


async def knowledge_version(sessionmaker: Sessionmaker) -> str:
    """Возвращает версию базы знаний: свёртка хешей всех записей из ``kb_documents``.

    Версия входит в ключ кеша ответов: после переиндексации базы старые закешированные ответы перестают
    использоваться.

    Args:
        sessionmaker: Фабрика асинхронных сессий.

    Returns:
        Короткая строка-версия; ``empty``, если база ещё не проиндексирована.
    """
    hashes = func.string_agg(KbDocument.content_hash, aggregate_order_by(literal_column("''"), KbDocument.slug))
    stmt = select(func.md5(hashes))
    async with sessionmaker() as session:
        digest = (await session.execute(stmt)).scalar_one_or_none()
    return digest[:12] if digest else "empty"
