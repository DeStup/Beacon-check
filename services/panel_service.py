"""Периодическая проверка и восстановление панелей в PANEL_CHANNEL_ID."""

from __future__ import annotations

import asyncio
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
    Проверяет панели: если сообщение удалили — создаёт заново.
    Живые сообщения не редактирует (только GET существования).
    """
    if not config.PANEL_CHANNEL_ID:
        return

    from services.beacon_service import refresh_beacon_panel
    from services.feed_service import refresh_feed_panel
    from services.relic_service import refresh_relic_panel
    from services.season_service import refresh_season_panel
    from services.upkeep_service import refresh_upkeep_panel

    jobs = (
        ("beacon", refresh_beacon_panel),
        ("upkeep", refresh_upkeep_panel),
        ("relic", refresh_relic_panel),
        ("season", refresh_season_panel),
        ("feed", refresh_feed_panel),
    )
    gap = config.PANEL_PATCH_GAP_SECONDS
    for index, (name, refresh) in enumerate(jobs):
        if index > 0 and gap > 0:
            await asyncio.sleep(gap)
        try:
            await refresh(bot, edit_existing=False)
        except Exception as exc:
            error_logger.error(
                f"ensure_all_panels failed for {name}: {exc}",
                exc_info=True,
            )


@tasks.loop(minutes=config.PANELS_ENSURE_INTERVAL_MINUTES)
async def maintain_panels(bot: BeaconBot) -> None:
    try:
        await ensure_all_panels(bot)
    except Exception as exc:
        error_msg = f"Ошибка в maintain_panels: {exc}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")


@maintain_panels.before_loop
async def _before_maintain_panels() -> None:
    await asyncio.sleep(config.PANELS_ENSURE_OFFSET_SEC)


def start_panel_tasks(bot: BeaconBot) -> None:
    if not maintain_panels.is_running():
        maintain_panels.start(bot)
        system_logger.info(
            "Panel maintain loop started "
            f"(every {config.PANELS_ENSURE_INTERVAL_MINUTES:g} min, "
            f"offset {config.PANELS_ENSURE_OFFSET_SEC:g}s, "
            f"gap {config.PANEL_PATCH_GAP_SECONDS:g}s)"
        )
