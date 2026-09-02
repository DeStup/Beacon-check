"""Настройка логирования."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import config


def setup_logging() -> tuple[logging.Logger, logging.Logger]:
    """Создаёт каталог логов и возвращает (action_logger, error_logger)."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    action = logging.getLogger("beacon_actions")
    if not action.handlers:
        handler = RotatingFileHandler(
            config.LOG_DIR / "actions.log",
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        action.addHandler(handler)
        action.setLevel(logging.INFO)

    errors = logging.getLogger("beacon_errors")
    if not errors.handlers:
        handler = RotatingFileHandler(
            config.LOG_DIR / "errors.log",
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        errors.addHandler(handler)
        errors.setLevel(logging.ERROR)

    return action, errors


action_logger, error_logger = setup_logging()
