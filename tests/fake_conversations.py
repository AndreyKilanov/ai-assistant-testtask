"""Подставное хранилище диалогов в памяти для тестов сервиса и API."""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from app.core.errors import ConversationNotFound
from app.domain.conversations import NEEDS_ATTENTION, ConversationRecord, MessageRecord, status_after_open
from app.schemas.analyze import AnalyzeResponse


class FakeConversationStore:
    def __init__(self) -> None:
        self.conversations: dict[int, ConversationRecord] = {}
        self.messages: list[MessageRecord] = []

    async def create(self, client_name: str | None) -> ConversationRecord:
        now = datetime.now(UTC)
        record = ConversationRecord(
            id=len(self.conversations) + 1,
            token=uuid.uuid4().hex,
            client_name=client_name,
            channel="web",
            status="new",
            contact_method=None,
            contact_value=None,
            preferred_time=None,
            contact_comment=None,
            contact_requested_at=None,
            manager_note="",
            unread_by_manager=0,
            last_message_preview="",
            last_message_at=now,
            created_at=now,
        )
        self.conversations[record.id] = record
        return record

    async def get(self, conversation_id: int) -> ConversationRecord | None:
        return self.conversations.get(conversation_id)

    async def get_by_token(self, token: str) -> ConversationRecord | None:
        return next((c for c in self.conversations.values() if c.token == token), None)

    async def add_message(
        self,
        conversation_id: int,
        sender: str,
        text: str,
        *,
        status: str | Callable[[str], str] | None = None,
        unread_delta: int = 0,
        suggestion_id: int | None = None,
        suggestion_state: str | None = None,
        edited: bool = False,
        auto: bool = False,
        links: list[dict[str, str]] | None = None,
        update_fields: Mapping[str, object] | None = None,
    ) -> MessageRecord:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise ConversationNotFound("Диалог не найден")
        if callable(status):
            status = status(conversation.status)
        now = datetime.now(UTC)
        message = MessageRecord(
            id=len(self.messages) + 1,
            conversation_id=conversation_id,
            sender=sender,
            text=text,
            suggestion_id=suggestion_id,
            suggestion_state=suggestion_state,
            edited=edited,
            created_at=now,
            auto=auto,
            links=links or [],
        )
        self.messages.append(message)
        self.conversations[conversation_id] = replace(
            conversation,
            **(update_fields or {}),
            last_message_preview=" ".join(text.split())[:160],
            last_message_at=now,
            unread_by_manager=conversation.unread_by_manager + unread_delta,
            status=status or conversation.status,
            hot=False if (sender == "manager" and not auto) or status == "closed" else conversation.hot,
        )
        return message

    async def get_message(self, message_id: int) -> MessageRecord | None:
        return next((m for m in self.messages if m.id == message_id), None)

    async def list_messages(
        self, conversation_id: int, after_id: int = 0, *, before_id: int | None = None, limit: int | None = None
    ) -> list[MessageRecord]:
        rows = [
            m
            for m in self.messages
            if m.conversation_id == conversation_id and m.id > after_id and (before_id is None or m.id < before_id)
        ]
        return rows if limit is None else rows[-limit:]

    async def mark_opened(self, conversation_id: int) -> ConversationRecord | None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        self.conversations[conversation_id] = replace(
            conversation, unread_by_manager=0, status=status_after_open(conversation.status)
        )
        return self.conversations[conversation_id]

    async def list_conversations(
        self, status: str | None, query: str | None, limit: int
    ) -> tuple[list[ConversationRecord], dict[str, int]]:
        rows = list(self.conversations.values())
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        if status:
            rows = [r for r in rows if r.status == status]
        if query:
            needle = query.casefold()
            rows = [
                r
                for r in rows
                if needle in (r.client_name or "").casefold() or needle in r.last_message_preview.casefold()
            ]
        rows.sort(
            key=lambda r: (not (r.hot and r.status != "closed"), r.status not in NEEDS_ATTENTION, -r.last_message_at.timestamp())
        )
        return rows[:limit], counts

    async def update(self, conversation_id: int, **fields: object) -> ConversationRecord | None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        self.conversations[conversation_id] = replace(conversation, **fields)
        return self.conversations[conversation_id]

    async def set_message_suggestion(self, message_id: int, suggestion_id: int | None, state: str) -> None:
        for index, message in enumerate(self.messages):
            if message.id == message_id:
                self.messages[index] = replace(message, suggestion_id=suggestion_id, suggestion_state=state)

    async def latest_client_message(self, conversation_id: int) -> MessageRecord | None:
        client = [m for m in self.messages if m.conversation_id == conversation_id and m.sender == "client"]
        return client[-1] if client else None

    async def unanswered_client_messages(self, since, limit: int) -> list[tuple[int, int]]:
        last: dict[int, MessageRecord] = {}
        for message in self.messages:
            if message.sender in {"client", "manager"}:
                last[message.conversation_id] = message
        rows = [(m.conversation_id, m.id) for m in last.values() if m.sender == "client" and m.created_at >= since]
        return sorted(rows, key=lambda row: row[1])[:limit]

    async def count_messages(self, conversation_id: int) -> tuple[int, int]:
        rows = [m for m in self.messages if m.conversation_id == conversation_id]
        return sum(m.sender in {"client", "manager"} for m in rows), sum(m.sender == "client" for m in rows)


class FakeSuggestionReader:
    def __init__(self, source=None) -> None:
        self.items: dict[int, AnalyzeResponse] = {}
        self.source = source

    async def get(self, suggestion_id: int) -> AnalyzeResponse | None:
        if suggestion_id in self.items:
            return self.items[suggestion_id]
        if self.source is not None and 0 < suggestion_id <= len(self.source.saved):
            return self.source.saved[suggestion_id - 1].model_copy(update={"suggestion_id": suggestion_id})
        return None
