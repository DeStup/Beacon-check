"""События жизненного цикла бота."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import config
from services.beacon_service import ensure_beacon_panel, start_background_tasks
from services.feed_service import ensure_feed_panel, start_feed_tasks
from services.panel_service import start_panel_tasks
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

        gap = config.PANEL_PATCH_GAP_SECONDS

        await ensure_beacon_panel(bot)
        await asyncio.sleep(gap)

        await ensure_upkeep_panel(bot)
        await asyncio.sleep(gap)

        await ensure_feed_panel(bot)
        await asyncio.sleep(gap)

        await bot.relic_timer.restore(bot)
        await ensure_relic_panel(bot)
        await asyncio.sleep(gap)

        await advance_due_seasons(bot)
        await ensure_season_panel(bot)
        await restart_season_watcher(bot)

        # Фоновые циклы после первичного ensure — со своими offset
        start_background_tasks(bot)
        start_upkeep_tasks(bot)
        start_feed_tasks(bot)
        start_panel_tasks(bot)
