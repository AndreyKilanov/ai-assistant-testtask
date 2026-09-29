import logging

from app.core.logging import RedactConversationToken

TOKEN = "a1b2c3d4" * 4


def make_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1", "GET", path, "1.1", 200), None
    )


def test_conversation_token_is_hidden_in_access_log() -> None:
    record = make_record(f"/api/chat/conversations/{TOKEN}/messages?after=0")

    assert RedactConversationToken().filter(record) is True

    assert TOKEN not in record.getMessage()
    assert "/api/chat/conversations/***/messages?after=0" in record.getMessage()


def test_other_paths_are_left_untouched() -> None:
    record = make_record("/api/manager/conversations/12")

    RedactConversationToken().filter(record)

    assert "/api/manager/conversations/12" in record.getMessage()
