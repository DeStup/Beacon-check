"""События жизненного цикла бота."""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.beacon_service import start_background_tasks
from utils.logging_setup import action_logger

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    @bot.event
    async def on_ready() -> None:
        print(f"Бот {bot.user} запущен!")
        action_logger.info(f"Bot {bot.user} started!")
        start_background_tasks(bot)
        restored = await bot.relic_timer.restore(bot)
        if restored:
            action_logger.info("Active relic timer restored from relic_events")
