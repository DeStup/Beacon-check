"""События жизненного цикла бота."""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.beacon_service import start_background_tasks
from services.relic_service import ensure_relic_panel
from services.season_service import (
    advance_due_seasons,
    ensure_season_panel,
    restart_season_watcher,
)
from services.upkeep_service import ensure_upkeep_panel, start_upkeep_tasks
from utils.logging_setup import system_logger

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    @bot.event
    async def on_ready() -> None:
        print(f"Бот {bot.user} запущен!")
        system_logger.info(f"Bot {bot.user} started!")
        start_background_tasks(bot)
        await ensure_upkeep_panel(bot)
        start_upkeep_tasks(bot)
        await bot.relic_timer.restore(bot)
        await ensure_relic_panel(bot)
        await advance_due_seasons(bot)
        await ensure_season_panel(bot)
        await restart_season_watcher(bot)
