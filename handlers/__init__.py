"""Регистрация обработчиков команд и событий."""

from __future__ import annotations

from typing import TYPE_CHECKING

from handlers import beacons, events, help as help_commands, relic, timers, upkeep

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    """Подключает все handlers к боту."""
    events.setup(bot)
    beacons.setup(bot)
    relic.setup(bot)
    timers.setup(bot)
    upkeep.setup(bot)
    help_commands.setup(bot)
