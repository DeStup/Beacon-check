"""Slash-команды сезонов."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

import config
from services.season_service import (
    clear_season,
    refresh_season_panel,
    restart_season_watcher,
    season_label,
    setup_season,
)
from utils.formatting import get_user_info
from utils.logging_setup import error_logger, season_logger
from utils.permissions import is_moderator

if TYPE_CHECKING:
    from bot import BeaconBot


def _format_elapsed(hours: int, minutes: int) -> str:
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes or not parts:
        parts.append(f"{minutes} мин")
    return " ".join(parts)


def setup(bot: BeaconBot) -> None:
    season = app_commands.Group(
        name="season",
        description="Игровые сезоны (24 часа)",
    )

    @season.command(
        name="setup",
        description="Начать сезон с указанием уже прошедшего времени",
    )
    @app_commands.describe(
        current="Какой сезон начать",
        hours="Сколько часов уже прошло с начала (по умолчанию 0)",
        minutes="Сколько минут уже прошло с начала (по умолчанию 0)",
    )
    @app_commands.choices(
        current=[
            app_commands.Choice(
                name=season_label(key),
                value=key,
            )
            for key in config.SEASON_KEYS
        ]
    )
    async def setup_cmd(
        interaction: discord.Interaction,
        current: app_commands.Choice[str],
        hours: Optional[app_commands.Range[int, 0, 24]] = None,
        minutes: Optional[app_commands.Range[int, 0, 59]] = None,
    ) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                "❌ Недостаточно прав (нужна модерация).",
                ephemeral=True,
            )
            return

        user_info = get_user_info(interaction)
        hrs = 0 if hours is None else int(hours)
        mins = 0 if minutes is None else int(minutes)
        total_minutes = hrs * 60 + mins

        if total_minutes > config.SEASON_DURATION_MINUTES:
            await interaction.response.send_message(
                f"❌ Суммарное время не больше "
                f"{config.SEASON_DURATION_MINUTES} мин "
                f"({config.SEASON_DURATION_HOURS:g} ч).",
                ephemeral=True,
            )
            return

        try:
            snap = setup_season(
                current.value,
                elapsed_minutes=total_minutes,
            )
        except ValueError as exc:
            await interaction.response.send_message(
                f"❌ {exc}",
                ephemeral=True,
            )
            return
        except Exception as exc:
            error_logger.error(
                f"{user_info} season setup failed: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(
                "❌ Не удалось сохранить сезон.",
                ephemeral=True,
            )
            return

        ends_unix = int(snap["ends_at"].timestamp())
        season_logger.info(
            f"{user_info} season setup → {snap['season_key']} "
            f"elapsed={hrs}h{mins}m ({total_minutes}m)"
        )
        embed = discord.Embed(
            title="Сезон настроен",
            description=f"**`{snap['label']}`**",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Закончится",
            value=f"<t:{ends_unix}:f> (<t:{ends_unix}:R>)",
            inline=False,
        )
        if total_minutes > 0:
            embed.add_field(
                name="Учтено времени",
                value=_format_elapsed(hrs, mins),
                inline=True,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await refresh_season_panel(bot)
        await restart_season_watcher(bot)

    @season.command(
        name="delete",
        description="Сбросить таймер сезонов и вернуть панель к исходному виду",
    )
    async def delete_cmd(interaction: discord.Interaction) -> None:
        if not is_moderator(interaction.user):
            await interaction.response.send_message(
                "❌ Недостаточно прав (нужна модерация).",
                ephemeral=True,
            )
            return

        user_info = get_user_info(interaction)
        had = clear_season()
        season_logger.info(
            f"{user_info} season delete "
            f"(had_state={had})"
        )
        await refresh_season_panel(bot)
        await restart_season_watcher(bot)

        if had:
            embed = discord.Embed(
                title="Сезон сброшен",
                description=(
                    "Таймер сезонов очищен.\n"
                    "Панель «Время» возвращена к исходному состоянию."
                ),
                color=discord.Color.orange(),
            )
        else:
            embed = discord.Embed(
                title="Сезон уже сброшен",
                description="Активного таймера сезонов не было.",
                color=discord.Color.dark_grey(),
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(season)
