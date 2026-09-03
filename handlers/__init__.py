"""Регистрация обработчиков команд и событий."""

from __future__ import annotations

from typing import TYPE_CHECKING

from handlers import beacons, events, relic, timers

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    """Подключает все handlers к боту."""
    events.setup(bot)
    beacons.setup(bot)
    relic.setup(bot)
    timers.setup(bot)
