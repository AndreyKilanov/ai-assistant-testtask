"""Отчёт по оценкам менеджеров: где подсказки не понравились и почему.

Используется для улучшения промптов и базы знаний: негативные оценки выводятся вместе с вопросом клиента, ответом,
подсказкой, использованными источниками и комментарием менеджера, а сводка группируется по версии промпта.
Запуск: ``python -m scripts.feedback_report [--limit 20]``.
"""

import argparse
import asyncio

from sqlalchemy import text

from app.db.session import get_sessionmaker

SUMMARY_SQL = text(
    """
    select s.prompt_version, s.model,
           count(*) filter (where f.rating = 1) as up,
           count(*) filter (where f.rating = -1) as down
    from feedback f join suggestions s on s.id = f.suggestion_id
    group by s.prompt_version, s.model order by s.prompt_version, s.model
    """
)
NEGATIVE_SQL = text(
    """
    select s.id, s.client_message, s.reply, s.upsell_hint, s.sources, f.comment, f.manager_id, f.created_at
    from feedback f join suggestions s on s.id = f.suggestion_id
    where f.rating = -1 order by f.created_at desc limit :limit
    """
)


async def report(limit: int) -> None:
    """Печатает сводку по версиям промпта и последние негативные оценки.

    Args:
        limit: Сколько негативных оценок показать.
    """
    async with get_sessionmaker()() as session:
        summary = (await session.execute(SUMMARY_SQL)).all()
        negatives = (await session.execute(NEGATIVE_SQL, {"limit": limit})).all()

    print("== Оценки по версиям промпта и моделям ==")
    for row in summary:
        total = row.up + row.down
        share = f"{row.down / total:.0%}"
        print(f"  промпт {row.prompt_version} | {row.model}: 👍 {row.up}  👎 {row.down}  (негативных {share})")
    if not summary:
        print("  оценок пока нет")

    print(f"\n== Последние негативные оценки (до {limit}) ==")
    for row in negatives:
        used = [source["entry_id"] for source in row.sources if source.get("used")]
        print(f"\n#{row.id} менеджер={row.manager_id or '-'} {row.created_at:%Y-%m-%d %H:%M}")
        print(f"  Клиент : {row.client_message}")
        print(f"  Ответ  : {row.reply}")
        print(f"  Допродажа: {row.upsell_hint}")
        print(f"  Источники: {', '.join(used) or 'нет'}")
        print(f"  Комментарий менеджера: {row.comment or '-'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="сколько негативных оценок показать")
    asyncio.run(report(parser.parse_args().limit))
