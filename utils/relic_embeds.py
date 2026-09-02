"""Embed и проверки канала для команд реликвии."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

import config
from utils.formatting import format_duration_minutes
from utils.logging_setup import error_logger

if TYPE_CHECKING:
    from bot import BeaconBot
    from services.relic_service import RelicTimer

RELIC_WARNING_TEXT = "За 10 минут до появления будет отправлено предупреждение"


def appear_unix_timestamp(minutes: int) -> int:
    return int((datetime.now() + timedelta(minutes=minutes)).timestamp())


def appear_unix_timestamp_at(dt: datetime) -> int:
    return int(dt.timestamp())


def add_relic_schedule_fields(
    embed: discord.Embed,
    channel_mention: str,
    unix_timestamp: int,
    *,
    channel_inline: bool = True,
) -> None:
    embed.add_field(
        name="📢 Уведомление",
        value=RELIC_WARNING_TEXT,
        inline=False,
    )
    embed.add_field(
        name="⏰ Время появления",
        value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
        inline=True,
    )
    embed.add_field(
        name="📌 Канал",
        value=channel_mention,
        inline=channel_inline,
    )


async def ensure_relic_channel(
    interaction: discord.Interaction,
    bot: BeaconBot,
    *,
    user_info: str,
    log_context: str,
) -> Optional[discord.abc.Messageable]:
    """Проверяет RELIC_CHANNEL_ID. При ошибке отвечает в interaction и возвращает None."""
    if config.RELIC_CHANNEL_ID == 0:
        await interaction.response.send_message(
            "❌ Канал для реликвий не настроен! "
            "Добавьте RELIC_CHANNEL_ID в .env файл.",
            ephemeral=True,
        )
        error_logger.error(
            f"{user_info} tried {log_context} but RELIC_CHANNEL_ID is not configured"
        )
        return None

    channel = bot.get_channel(config.RELIC_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(
            f"❌ Канал с ID {config.RELIC_CHANNEL_ID} не найден! "
            "Проверьте настройки.",
            ephemeral=True,
        )
        error_logger.error(
            f"{user_info} tried {log_context} but channel "
            f"{config.RELIC_CHANNEL_ID} not found"
        )
        return None

    return channel


def build_relic_started_embed(
    channel: discord.abc.Messageable,
    minutes: int,
    *,
    started_by: Optional[str] = None,
) -> discord.Embed:
    time_str = format_duration_minutes(minutes)
    embed = discord.Embed(
        title="⏳ Таймер реликвии запущен",
        description=f"Реликвия появится через **{time_str}**",
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )
    add_relic_schedule_fields(
        embed,
        channel.mention,
        appear_unix_timestamp(minutes),
        channel_inline=True,
    )
    embed.add_field(name="📊 Статус", value="🟢 Активен", inline=True)
    if started_by:
        embed.set_footer(text=f"Запустил: {started_by}")
    return embed


def build_relic_restarted_embed(
    channel: discord.abc.Messageable,
    minutes: int,
) -> discord.Embed:
    time_str = format_duration_minutes(minutes)
    embed = discord.Embed(
        title="🔄 Таймер перезапущен",
        description=f"Таймер появления реликвии перезапущен на **{time_str}**",
        color=discord.Color.blue(),
        timestamp=datetime.now(),
    )
    add_relic_schedule_fields(
        embed,
        channel.mention,
        appear_unix_timestamp(minutes),
        channel_inline=False,
    )
    return embed


def build_relic_already_running_embed(
    channel: discord.abc.Messageable,
    timer: RelicTimer,
) -> discord.Embed:
    embed = discord.Embed(
        title="⏳ Таймер уже запущен",
        description=(
            f"В канале {channel.mention} уже запущен "
            "таймер появления реликвии."
        ),
        color=discord.Color.orange(),
        timestamp=datetime.now(),
    )
    embed.add_field(
        name="⏱️ Оставшееся время",
        value=f"**{timer.get_remaining_time_formatted()}**",
        inline=False,
    )
    if timer.timer_start_time and timer.timer_duration:
        appear_time = timer.timer_start_time + timedelta(
            minutes=timer.timer_duration
        )
        unix_timestamp = appear_unix_timestamp_at(appear_time)
        embed.add_field(
            name="⏰ Примерное время появления",
            value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
            inline=False,
        )
    embed.add_field(
        name="🔄 Что делать?",
        value=(
            "Отмените текущий таймер или нажмите **Перезапустить** "
            "и введите нужное число минут."
        ),
        inline=False,
    )
    return embed


def build_relic_cancelled_embed(
    description: str = "Таймер появления реликвии был отменен.",
) -> discord.Embed:
    return discord.Embed(
        title="⏹️ Таймер отменен",
        description=description,
        color=discord.Color.red(),
        timestamp=datetime.now(),
    )


def build_relic_active_status_embed(
    channel: discord.abc.Messageable,
    timer: RelicTimer,
) -> discord.Embed:
    embed = discord.Embed(
        title="⏳ Таймер реликвии активен",
        description=(
            f"В канале {channel.mention} запущен "
            "таймер появления реликвии."
        ),
        color=discord.Color.green(),
        timestamp=datetime.now(),
    )
    embed.add_field(
        name="⏱️ Оставшееся время",
        value=f"**{timer.get_remaining_time_formatted()}**",
        inline=False,
    )
    embed.add_field(
        name="📢 Уведомление",
        value=RELIC_WARNING_TEXT,
        inline=True,
    )
    embed.add_field(
        name="📌 Канал",
        value=channel.mention,
        inline=True,
    )
    if timer.timer_start_time and timer.timer_duration:
        appear_time = timer.timer_start_time + timedelta(
            minutes=timer.timer_duration
        )
        unix_timestamp = appear_unix_timestamp_at(appear_time)
        embed.add_field(
            name="⏰ Примерное время появления",
            value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
            inline=False,
        )
    return embed


def build_relic_inactive_embed() -> discord.Embed:
    embed = discord.Embed(
        title="❌ Таймер не активен",
        description="Нет запущенного таймера реликвии.",
        color=discord.Color.red(),
    )
    embed.add_field(
        name="💡 Запустить таймер",
        value="Используйте команду `/relic start` для запуска таймера",
        inline=False,
    )
    return embed
