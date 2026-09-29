"""Репозиторий оценок менеджеров (таблица ``feedback``)."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import SuggestionNotFound
from app.db.models import Feedback, Suggestion
from app.db.session import Sessionmaker


class FeedbackRepository:
    """Хранилище оценок менеджеров в таблице ``feedback`` (реализует порт FeedbackStore).

    Attributes:
        sessionmaker: Фабрика асинхронных сессий.
    """

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        """Запоминает фабрику сессий.

        Args:
            sessionmaker: Фабрика асинхронных сессий SQLAlchemy.
        """
        self.sessionmaker = sessionmaker

    async def save(self, suggestion_id: int, rating: int, comment: str | None, manager_id: str | None) -> int:
        """Сохраняет оценку; повторная оценка того же менеджера обновляет прежнюю.

        Args:
            suggestion_id: Оцениваемая подсказка.
            rating: 1 или -1.
            comment: Комментарий менеджера.
            manager_id: Идентификатор менеджера.

        Returns:
            Идентификатор оценки.

        Raises:
            SuggestionNotFound: Подсказки с таким идентификатором нет.
        """
        values = {"suggestion_id": suggestion_id, "rating": rating, "comment": comment, "manager_id": manager_id}
        stmt = insert(Feedback).values(**values)
        if manager_id is not None:
            stmt = stmt.on_conflict_do_update(
                index_elements=["suggestion_id", "manager_id"],
                index_where=Feedback.manager_id.isnot(None),
                set_={"rating": rating, "comment": comment, "created_at": func.now()},
            )
        async with self.sessionmaker() as session:
            if await session.scalar(select(Suggestion.id).where(Suggestion.id == suggestion_id)) is None:
                raise SuggestionNotFound(f"Подсказка {suggestion_id} не найдена")
            feedback_id = (await session.execute(stmt.returning(Feedback.id))).scalar_one()
            await session.commit()
        return feedback_id
