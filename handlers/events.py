"""События жизненного цикла бота."""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.beacon_service import start_background_tasks
from services.upkeep_service import start_upkeep_tasks
from utils.logging_setup import system_logger

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    @bot.event
    async def on_ready() -> None:
        print(f"Бот {bot.user} запущен!")
        system_logger.info(f"Bot {bot.user} started!")
        start_background_tasks(bot)
        start_upkeep_tasks(bot)
        await bot.relic_timer.restore(bot)
        await bot.timer_manager.restore_all(bot)
