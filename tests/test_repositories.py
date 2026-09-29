import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.repositories import Sessionmaker, SuggestionRepository, WebhookEventRepository, knowledge_version
from tests.fakes import make_response


@pytest.fixture
async def sessionmaker() -> AsyncIterator[Sessionmaker]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except OSError:
        await engine.dispose()
        pytest.skip("Postgres недоступен")
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def test_webhook_event_lifecycle(sessionmaker: Sessionmaker) -> None:
    repo = WebhookEventRepository(sessionmaker)
    event_id = f"test-{uuid.uuid4()}"

    assert await repo.create(event_id, {"message": "привет"}) is True
    assert await repo.create(event_id, {"message": "повтор"}) is False

    record = await repo.get(event_id)
    assert record is not None and record.status == "received" and record.payload == {"message": "привет"}

    await repo.set_status(event_id, "processed")
    assert (await repo.get(event_id)).status == "processed"

    await repo.delete(event_id)
    assert await repo.get(event_id) is None


async def test_suggestion_is_saved_with_cache_flag(sessionmaker: Sessionmaker) -> None:
    repo = SuggestionRepository(sessionmaker)
    response = (await make_response()).model_copy(update={"cache_status": "hit"})

    suggestion_id = await repo.save("test-lead", "Сколько стоит цеолит Макс?", response)

    assert isinstance(suggestion_id, int)
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text("select cache_hit, lead_id from suggestions where id = :i"), {"i": suggestion_id}
            )
        ).one()
        assert (row.cache_hit, row.lead_id) == (True, "test-lead")
        await session.execute(text("delete from suggestions where id = :i"), {"i": suggestion_id})
        await session.commit()


async def test_knowledge_version_is_stable_short_string(sessionmaker: Sessionmaker) -> None:
    first = await knowledge_version(sessionmaker)

    assert first == await knowledge_version(sessionmaker)
    assert first == "empty" or len(first) == 12


async def _new_suggestion(sessionmaker: Sessionmaker, cache_status: str = "miss") -> int:
    response = (await make_response()).model_copy(update={"cache_status": cache_status})
    suggestion_id = await SuggestionRepository(sessionmaker).save("test-fb", "Сколько стоит цеолит Макс?", response)
    assert suggestion_id is not None
    return suggestion_id


async def _cleanup(sessionmaker: Sessionmaker, *suggestion_ids: int) -> None:
    async with sessionmaker() as session:
        await session.execute(text("delete from suggestions where id = any(:ids)"), {"ids": list(suggestion_ids)})
        await session.commit()


async def test_feedback_upserts_per_manager_and_rejects_unknown_suggestion(sessionmaker: Sessionmaker) -> None:
    from app.core.errors import SuggestionNotFound
    from app.db.repositories import FeedbackRepository

    repo = FeedbackRepository(sessionmaker)
    suggestion_id = await _new_suggestion(sessionmaker)
    try:
        first = await repo.save(suggestion_id, 1, None, "manager-1")
        second = await repo.save(suggestion_id, -1, "Неверная цена", "manager-1")
        other = await repo.save(suggestion_id, 1, None, "manager-2")
        anonymous_a = await repo.save(suggestion_id, 1, None, None)
        anonymous_b = await repo.save(suggestion_id, -1, None, None)

        assert first == second and len({first, other, anonymous_a, anonymous_b}) == 4
        async with sessionmaker() as session:
            rows = (
                await session.execute(
                    text("select manager_id, rating from feedback where suggestion_id = :i"), {"i": suggestion_id}
                )
            ).all()
        assert sorted(rows, key=lambda r: str(r.manager_id)) == sorted(
            [("manager-1", -1), ("manager-2", 1), (None, 1), (None, -1)], key=lambda r: str(r[0])
        )
        with pytest.raises(SuggestionNotFound):
            await repo.save(999_999_999, 1, None, "manager-1")
    finally:
        await _cleanup(sessionmaker, suggestion_id)


async def test_stats_count_cache_hits_tokens_and_feedback(sessionmaker: Sessionmaker) -> None:
    from app.db.repositories import FeedbackRepository, StatsRepository

    stats = StatsRepository(sessionmaker, daily_llm_limit=500)
    before = await stats.today()
    miss_id = await _new_suggestion(sessionmaker, "miss")
    hit_id = await _new_suggestion(sessionmaker, "hit")
    try:
        await FeedbackRepository(sessionmaker).save(miss_id, -1, "плохо", "stats-manager")
        after = await stats.today()

        assert after.requests_total == before.requests_total + 2
        assert after.cache_hits == before.cache_hits + 1 and after.llm_calls == before.llm_calls + 1
        assert after.tokens_in == before.tokens_in + 200
        assert after.feedback_negative == before.feedback_negative + 1
        assert after.daily_llm_limit == 500 and 0 <= after.cache_hit_ratio <= 1
    finally:
        await _cleanup(sessionmaker, miss_id, hit_id)
