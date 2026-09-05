"""Discord-клиент бота."""

from __future__ import annotations

import discord
from discord import app_commands

import config
from services.relic_service import RelicTimer


class BeaconBot(discord.Client):
    """Клиент со slash CommandTree и таймером реликвии."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.relic_timer = RelicTimer(config.RELIC_CHANNEL_ID)

    async def setup_hook(self) -> None:
        from handlers import setup as setup_handlers

        setup_handlers(self)

        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
