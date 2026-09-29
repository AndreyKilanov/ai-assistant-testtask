"""Настройка логирования процесса."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Включает единый формат логов для API и worker.

    Args:
        level: Уровень логирования корневого логгера.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
