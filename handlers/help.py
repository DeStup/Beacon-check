"""Slash-команда /help — список команд бота."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

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
            value=(
                "`/beacon add` — добавить новый маяк\n"
                "`/beacon menu` — меню управления маяками\n"
                "`/beacon refuel` — пополнить топливо маяка\n"
                "`/beacon status` — статус маяка\n"
                "`/beacon edit` — редактировать маяк\n"
                "`/beacon delete` — удалить маяк\n"
                "`/beacon clear` — удалить все маяки (модерация)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Таймер Реликвии",
            value=(
                "`/relic start` — запустить таймер появления Реликвии "
                "(по умолчанию 90 минут)\n"
                "`/relic cancel` — отменить таймер Реликвии\n"
                "`/relic status` — статус таймера Реликвии"
            ),
            inline=False,
        )
        embed.add_field(
            name="Таймер",
            value=(
                "`/timer add` — создать таймер "
                "(день/час/минута, уведомление по выбору)\n"
                "`/timer status` — все активные таймеры"
            ),
            inline=False,
        )
        embed.add_field(
            name="Содержание",
            value=(
                "`/upkeep status` — создать или обновить "
                "панель Новгорода в канале"
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
