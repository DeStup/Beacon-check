"""Настройка логирования."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import config


def setup_logging() -> tuple[
    logging.Logger,
    logging.Logger,
    logging.Logger,
    logging.Logger,
    logging.Logger,
    logging.Logger,
]:
    """Возвращает (action, error, relic, system, timer, upkeep) loggers."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    action = logging.getLogger("beacon_actions")
    relic = logging.getLogger("relic_actions")
    timer = logging.getLogger("timer_actions")
    upkeep = logging.getLogger("upkeep_actions")
    system = logging.getLogger("system")
    errors = logging.getLogger("beacon_errors")

    if not action.handlers:
        action_handler = RotatingFileHandler(
            config.LOG_DIR / "actions.log",
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        action_handler.setFormatter(formatter)
        action.addHandler(action_handler)
        action.setLevel(logging.INFO)

        # Один файл actions.log: beacon | relic | timer | upkeep | system
        for logger in (relic, timer, upkeep, system):
            logger.addHandler(action_handler)
            logger.setLevel(logging.INFO)
    else:
        shared = action.handlers[0]
        for logger in (timer, upkeep):
            if not logger.handlers:
                logger.addHandler(shared)
                logger.setLevel(logging.INFO)

    if not errors.handlers:
        error_handler = RotatingFileHandler(
            config.LOG_DIR / "errors.log",
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        error_handler.setFormatter(formatter)
        errors.addHandler(error_handler)
        errors.setLevel(logging.ERROR)

    return action, errors, relic, system, timer, upkeep


(
    action_logger,
    error_logger,
    relic_logger,
    system_logger,
    timer_logger,
    upkeep_logger,
) = setup_logging()
