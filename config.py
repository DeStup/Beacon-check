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
# Ссылка на сообщение с подпиской/отпиской на роли уведомлений о реликвии
RELIC_LINK_MESSAGE_ROLES: str = (
    os.getenv("RELIC_LINK_MESSAGE_ROLES")
    or os.getenv("RELIC_NOTIFY_MESSAGE_URL")
    or os.getenv("RELIC_NOTIFY_MESSAGE_ID")
    or ""
).strip()
# Роль для пинга в предупреждении «реликвия скоро появится»
RELIC_QRF_ROLE_ID: int = int(os.getenv("RELIC_QRF_ROLE_ID", "0"))
# Канал алертов: ALERT_CHANNEL_ID или legacy ALERT_ROLE_ID в .env
ALERT_CHANNEL_ID: int = int(
    os.getenv("ALERT_CHANNEL_ID", os.getenv("ALERT_ROLE_ID", "0"))
)
# Канал предупреждений по upkeep (серебро)
UPKEEP_ALERT_CHANNEL_ID: int = int(os.getenv("UPKEEP_ALERT_CHANNEL_ID", "0"))
# Канал постоянных панелей (Владения Новгорода, реликвия); legacy UPKEEP_PANEL_CHANNEL_ID
PANEL_CHANNEL_ID: int = int(
    os.getenv("PANEL_CHANNEL_ID")
    or os.getenv("UPKEEP_PANEL_CHANNEL_ID", "0")
)
# Канал уведомлений о смене сезона
SEASON_ALERT_CHANNEL_ID: int = int(os.getenv("SEASON_ALERT_CHANNEL_ID", "0"))
# Канал предупреждений по кормёжке (животные)
FEED_ALERT_CHANNEL_ID: int = int(os.getenv("FEED_ALERT_CHANNEL_ID", "0"))

# Кастомные эмодзи (Discord snowflake ID)
SILVER_EMOJI_ID: int = int(os.getenv("SILVER_EMOJI_ID", "0"))


def custom_emoji(name: str, emoji_id: int) -> str:
    """Маркер кастомного эмодзи Discord или текстовый fallback."""
    if emoji_id:
        return f"<:{name}:{emoji_id}>"
    return name


SILVER_EMOJI: str = custom_emoji("silver", SILVER_EMOJI_ID)

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
# Сколько минут после появления реликвии держать таймер на панели
RELIC_PANEL_HOLD_MINUTES: int = 5

MAX_TIMER_NAME_LENGTH: int = 50
MAX_TIMER_SECONDS: int = 7 * 24 * 60 * 60  # 7 дней

MAX_UPKEEP_NAME_LENGTH: int = 50
UPKEEP_WARNING_HOURS: float = 3.0

# Кормёжка: животные
MAX_FEED_NAME_LENGTH: int = 50
FEED_MAX_SATIETY: float = 100.0
FEED_WARNING_THRESHOLD: float = 20.0
# Часы до полной потери сытости с 100%
FEED_ANIMAL_HOURS_TO_EMPTY: dict[str, float] = {
    "horse": 1.5,
    "donkey": 3.0,
}
FEED_ANIMAL_LABELS: dict[str, str] = {
    "horse": "Лошадь",
    "donkey": "Осёл",
}
FEED_ANIMAL_EMOJIS: dict[str, str] = {
    "horse": "🐴",
    "donkey": "🫏",
}

# Сезоны: порядок Lencten → Sumor → Harvest → Winter; война стартует в Harvest
SEASON_DURATION_HOURS: float = 24.0
SEASON_DURATION_MINUTES: int = 24 * 60  # 1440
SEASON_KEYS: tuple[str, ...] = (
    "lencten",
    "sumor",
    "harvest",
    "winter",
)
SEASON_LABELS: dict[str, str] = {
    "lencten": "Lencten (Весна)",
    "sumor": "Sumor (Лето)",
    "harvest": "Harvest (Осень)",
    "winter": "Winter (Зима)",
}
SEASON_EMOJIS: dict[str, str] = {
    "lencten": "🌱",
    "sumor": "☀️",
    "harvest": "🍂",
    "winter": "❄️",
}
SEASON_COLORS: dict[str, int] = {
    "lencten": 0x57F287,  # green
    "sumor": 0xFEE75C,  # yellow
    "harvest": 0xE67E22,  # orange
    "winter": 0x3498DB,  # blue
}
SEASON_WAR_START_KEY: str = "harvest"

# Игровые сутки (реальные минуты): 45 день + 15 ночь
DAY_CYCLE_MINUTES: int = 60
DAYLIGHT_MINUTES: int = 45
NIGHT_MINUTES: int = 15  # DAY_CYCLE_MINUTES - DAYLIGHT_MINUTES

# Пользователи с правом /beacon clear вне админ-прав гильдии
CLEAR_ALLOWED_USER_IDS: frozenset[int] = frozenset({226751097295994881})

LOG_MAX_BYTES: int = 10 * 1024 * 1024
LOG_BACKUP_COUNT: int = 5
