"""Точка входа Discord-бота beaconMonitor."""

from __future__ import annotations

import sys

import config
from bot import BeaconBot
from services.database import init_db
from utils.logging_setup import error_logger, system_logger


def main() -> None:
    if not config.TOKEN:
        print("Ошибка: TOKEN не задан в .env", file=sys.stderr)
        sys.exit(1)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    bot = BeaconBot()
    system_logger.info("Starting BeaconBot...")
    try:
        bot.run(config.TOKEN)
    except Exception:
        error_logger.exception("Bot crashed")
        raise


if __name__ == "__main__":
    main()
