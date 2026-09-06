"""Slash-команда /help — список команд бота."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

import config

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    @bot.tree.command(name="help", description="Список команд бота")
    async def help_command(interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Справка по командам",
            description="Доступные slash-команды, сгруппированные по разделам.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Маяки",
            value="`/beacon add` — добавить новый маяк",
            inline=False,
        )
        embed.add_field(
            name="Таймер Реликвии",
            value=(
                "`/relic start` — запустить таймер появления Реликвии "
                f"(мин. {config.MIN_RELIC_MINUTES}, по умолчанию "
                f"{config.DEFAULT_RELIC_MINUTES} минут)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Сезоны",
            value=(
                "`/season setup` — начать сезон "
                "(модерация; можно указать, сколько часов/минут уже прошло)\n"
                "`/season delete` — сбросить таймер сезонов (модерация)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Прочее",
            value=(
                "`/ping` — проверка, что бот жив\n"
                "`/help` — эта справка"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
