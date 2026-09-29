"""Сводная статистика по таблицам ``suggestions`` и ``feedback``."""

from datetime import UTC, datetime

from sqlalchemy import text

from app.db.session import Sessionmaker
from app.schemas.stats import StatsResponse


class StatsRepository:
    """Сводная статистика по таблицам ``suggestions`` и ``feedback`` (реализует порт StatsProvider).

    Attributes:
        sessionmaker: Фабрика асинхронных сессий.
        daily_llm_limit: Дневной бюджет обращений к модели (для отчёта).
    """

    def __init__(self, sessionmaker: Sessionmaker, daily_llm_limit: int) -> None:
        """Запоминает зависимости.

        Args:
            sessionmaker: Фабрика асинхронных сессий SQLAlchemy.
            daily_llm_limit: Дневной бюджет обращений к модели.
        """
        self.sessionmaker = sessionmaker
        self.daily_llm_limit = daily_llm_limit

    async def today(self) -> StatsResponse:
        """Считает статистику за текущие сутки (UTC).

        Returns:
            Сводка по подсказкам, токенам, кешу и оценкам.
        """
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        suggestions = text(
            """
            select count(*) as total,
                   count(*) filter (where cache_hit) as hits,
                   coalesce(sum(tokens_in), 0) as tokens_in,
                   coalesce(sum(tokens_out), 0) as tokens_out,
                   avg(latency_ms) filter (where not cache_hit) as avg_llm,
                   avg(latency_ms) filter (where cache_hit) as avg_cache
            from suggestions where created_at >= :start
            """
        )
        feedback = text(
            """
            select count(*) filter (where rating = 1) as up, count(*) filter (where rating = -1) as down
            from feedback where created_at >= :start
            """
        )
        async with self.sessionmaker() as session:
            row = (await session.execute(suggestions, {"start": start})).one()
            votes = (await session.execute(feedback, {"start": start})).one()
        return StatsResponse(
            date=start.date().isoformat(),
            requests_total=row.total,
            cache_hits=row.hits,
            llm_calls=row.total - row.hits,
            cache_hit_ratio=round(row.hits / row.total, 3) if row.total else 0.0,
            tokens_in=int(row.tokens_in),
            tokens_out=int(row.tokens_out),
            avg_latency_llm_ms=None if row.avg_llm is None else round(float(row.avg_llm), 1),
            avg_latency_cache_ms=None if row.avg_cache is None else round(float(row.avg_cache), 1),
            daily_llm_limit=self.daily_llm_limit,
            feedback_positive=votes.up,
            feedback_negative=votes.down,
        )
