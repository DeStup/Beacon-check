"""Сервисный слой: БД, маяки, реликвии, upkeep."""

from services.database import init_db
from services.relic_service import RelicTimer

__all__ = ["RelicTimer", "init_db"]
