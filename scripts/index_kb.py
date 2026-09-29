"""Индексация data/knowledge_base.json в pgvector.

Сравнивает хеши записей с таблицей ``kb_documents`` и переиндексирует только новые, изменённые и удалённые записи.
Запуск: ``python -m scripts.index_kb`` (нужны Postgres и сервис эмбеддингов TEI).
"""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.db.models import KbDocument
from app.db.session import get_sessionmaker
from app.integrations.rag.index import KnowledgeIndex, entry_hash

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.json"


async def sync(force: bool) -> None:
    """Приводит индекс pgvector и таблицу kb_documents в соответствие с базой знаний.

    Args:
        force: Переиндексировать все записи независимо от хешей.
    """
    entries = {entry["id"]: entry for entry in json.loads(KB_PATH.read_text(encoding="utf-8"))}
    hashes = {entry_id: entry_hash(entry) for entry_id, entry in entries.items()}

    async with get_sessionmaker()() as session:
        known = dict((await session.execute(select(KbDocument.slug, KbDocument.content_hash))).all())
        removed = [slug for slug in known if slug not in entries]
        changed = [slug for slug, digest in hashes.items() if force or known.get(slug) != digest]

        knowledge = KnowledgeIndex(get_settings())
        await asyncio.to_thread(knowledge.remove, removed + [slug for slug in changed if slug in known])
        await asyncio.to_thread(knowledge.add, [entries[slug] for slug in changed])

        if removed:
            await session.execute(delete(KbDocument).where(KbDocument.slug.in_(removed)))
        for slug in changed:
            entry = entries[slug]
            values = {
                "slug": slug,
                "title": entry["title"],
                "category": entry["category"],
                "source_url": entry["source_url"],
                "content_hash": hashes[slug],
                "sensitive": entry["sensitive"],
            }
            upsert = insert(KbDocument).values(**values)
            await session.execute(upsert.on_conflict_do_update(index_elements=["slug"], set_=values))
        await session.commit()

    print(f"записей: {len(entries)} | проиндексировано: {len(changed)} | удалено: {len(removed)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="переиндексировать все записи")
    asyncio.run(sync(parser.parse_args().force))
