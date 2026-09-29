"""Настройка логирования процесса."""

import logging
import re

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
TOKEN_IN_PATH_RE = re.compile(r"(/api/chat/conversations/)[0-9a-f]{32}")


class RedactConversationToken(logging.Filter):
    """Прячет токен клиентского диалога в записях access-лога: по токену можно войти в чужой чат."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Заменяет токен в тексте и аргументах записи.

        Args:
            record: Запись лога.

        Returns:
            Всегда True: запись не отбрасывается.
        """
        if isinstance(record.args, tuple):
            record.args = tuple(
                TOKEN_IN_PATH_RE.sub(r"\1***", arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Включает единый формат логов для API и worker и скрывает токены диалогов в access-логе uvicorn.

    Args:
        level: Уровень логирования корневого логгера.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactConversationToken) for f in access_logger.filters):
        access_logger.addFilter(RedactConversationToken())
