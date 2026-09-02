"""Конфигурация бота и игровые константы."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "beacons.db"

TOKEN: str | None = os.getenv("TOKEN")
GUILD_ID: int = int(os.getenv("GUILD", "0"))
RELIC_CHANNEL_ID: int = int(os.getenv("RELIC_CHANNEL_ID", "0"))
# В .env называется ALERT_ROLE_ID, но в коде используется как ID канала алертов
ALERT_CHANNEL_ID: int = int(os.getenv("ALERT_ROLE_ID", "0"))

MAX_FUEL: float = 30.0
MAX_LIFETIME: float = 100.0

# Часы на 1 единицу топлива (priority 1 / 2 / 3)
PRIORITY_RATES: dict[int, float] = {
    1: 1.0,
    2: 1.5,
    3: 2.0,
}

LIFETIME_DECAY_RATE: float = 100.0 / 48.0  # % в час при наличии топлива
ACCELERATED_DECAY_RATE: float = 360.0  # % в час без топлива

WARNING_THRESHOLD: float = 20.0
CRITICAL_THRESHOLD: float = 5.0

DEFAULT_RELIC_MINUTES: int = 90
MAX_RELIC_MINUTES: int = 1440
RELIC_WARNING_MINUTES: int = 10

# Пользователи с правом /beacon clear вне админ-прав гильдии
CLEAR_ALLOWED_USER_IDS: frozenset[int] = frozenset({226751097295994881})

LOG_MAX_BYTES: int = 10 * 1024 * 1024
LOG_BACKUP_COUNT: int = 5
