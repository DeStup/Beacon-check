"""Периодическая проверка и восстановление панелей в PANEL_CHANNEL_ID."""

from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import tasks

import config
from utils.logging_setup import error_logger, system_logger

if TYPE_CHECKING:
    from bot import BeaconBot


def is_unknown_message(exc: BaseException) -> bool:
    """Сообщение удалено / не найдено."""
    import discord

    if isinstance(exc, discord.NotFound):
        return True
    if isinstance(exc, discord.HTTPException):
        if getattr(exc, "code", None) == 10008:
            return True
        if getattr(exc, "status", None) == 404:
            return True
    return False


async def ensure_all_panels(bot: BeaconBot) -> None:
    """
    Проверяет все панели: если сообщение удалили —
    refresh_* создаст его заново внизу канала.
    """
    if not config.PANEL_CHANNEL_ID:
        return

    from services.feed_service import refresh_feed_panel
    from services.relic_service import refresh_relic_panel
    from services.season_service import refresh_season_panel
    from services.upkeep_service import refresh_upkeep_panel

    for name, coro in (
        ("upkeep", refresh_upkeep_panel(bot)),
        ("relic", refresh_relic_panel(bot)),
        ("season", refresh_season_panel(bot)),
        ("feed", refresh_feed_panel(bot)),
    ):
        try:
            await coro
        except Exception as exc:
            error_logger.error(
                f"ensure_all_panels failed for {name}: {exc}",
                exc_info=True,
            )


@tasks.loop(minutes=2)
async def maintain_panels(bot: BeaconBot) -> None:
    try:
        await ensure_all_panels(bot)
    except Exception as exc:
        error_msg = f"Ошибка в maintain_panels: {exc}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")


def start_panel_tasks(bot: BeaconBot) -> None:
    if not maintain_panels.is_running():
        maintain_panels.start(bot)
        system_logger.info("Panel maintain loop started (every 2 min)")
