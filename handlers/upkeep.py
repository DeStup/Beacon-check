"""Slash-команды мониторинга содержания (серебро)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from handlers.views.upkeep_views import show_all_upkeep_status

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    upkeep = app_commands.Group(
        name="upkeep",
        description="Мониторинг содержания (серебро)",
    )

    @upkeep.command(
        name="status",
        description="Создать или обновить панель Новгорода в канале",
    )
    async def status(interaction: discord.Interaction) -> None:
        await show_all_upkeep_status(interaction)

    bot.tree.add_command(upkeep)
