"""Embed и проверки канала для команд реликвии."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

import config
from utils.logging_setup import error_logger

if TYPE_CHECKING:
    from bot import BeaconBot
    from services.relic_service import RelicTimer

RELIC_WARNING_TEXT = "За 10 минут до появления будет отправлено предупреждение"


def appear_unix_timestamp(minutes: int) -> int:
    return int((datetime.now() + timedelta(minutes=minutes)).timestamp())


def appear_unix_timestamp_at(dt: datetime) -> int:
    return int(dt.timestamp())


def relic_notify_subscribe_text() -> Optional[str]:
    """Текст про подписку на роль уведомлений; None если ссылка не задана."""
    url = config.RELIC_LINK_MESSAGE_ROLES
    if not url:
        return None
    return (
        "Подписаться на пинги QRF или отписаться - "
        f"[здесь]({url})"
    )


def notification_field_value() -> str:
    subscribe = relic_notify_subscribe_text()
    if subscribe:
        return f"{RELIC_WARNING_TEXT}\n{subscribe}"
    return RELIC_WARNING_TEXT


def build_relic_warning_embed(
    unix_timestamp: int,
    *,
    started_by: Optional[str] = None,
) -> discord.Embed:
    prepare = "Соберите отряд и подготовьте снаряжение!"
    subscribe = relic_notify_subscribe_text()
    if subscribe:
        prepare = f"{prepare}\n{subscribe}"

    embed = discord.Embed(
        title="⚔️ РЕЛИКВИЯ СКОРО ПОЯВИТСЯ!",
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )
    embed.add_field(
        name="📢 Приготовьтесь!",
        value=prepare,
        inline=True,
    )
    embed.add_field(
        name="⏰ Время появления",
        value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
        inline=False,
    )
    if started_by:
        embed.set_footer(text=f"Запустил: {started_by}")
    return embed


def relic_qrf_ping_content() -> Optional[str]:
    """Контент для реального пинга роли (упоминания в embed не пингуют)."""
    if not config.RELIC_QRF_ROLE_ID:
        return None
    return f"<@&{config.RELIC_QRF_ROLE_ID}>"


def add_relic_schedule_fields(
    embed: discord.Embed,
    channel_mention: str,
    unix_timestamp: int,
    *,
    channel_inline: bool = True,
    include_channel: bool = True,
) -> None:
    embed.add_field(
        name="📢 Уведомление",
        value=notification_field_value(),
        inline=False,
    )
    embed.add_field(
        name="⏰ Время появления",
        value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
        inline=True,
    )
    if include_channel:
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
    embed = discord.Embed(
        title="⏳ Таймер Реликвии запущен",
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )
    add_relic_schedule_fields(
        embed,
        channel.mention,
        appear_unix_timestamp(minutes),
        include_channel=False,
    )
    if started_by:
        embed.set_footer(text=f"Запустил: {started_by}")
    return embed


def build_relic_restarted_embed(
    channel: discord.abc.Messageable,
    minutes: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="🔄 Таймер Реликвии перезапущен",
        color=discord.Color.blue(),
        timestamp=datetime.now(),
    )
    add_relic_schedule_fields(
        embed,
        channel.mention,
        appear_unix_timestamp(minutes),
        include_channel=False,
    )
    return embed


def build_relic_already_running_embed(
    _channel: discord.abc.Messageable,
    timer: RelicTimer,
) -> discord.Embed:
    embed = discord.Embed(
        title="⏳ Таймер Реликвии уже запущен",
        color=discord.Color.orange(),
        timestamp=datetime.now(),
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


def build_relic_cancelled_embed(
    description: str = "Таймер появления Реликвии был отменен.",
) -> discord.Embed:
    return discord.Embed(
        title="⏹️ Таймер Реликвии отменен",
        description=description,
        color=discord.Color.red(),
        timestamp=datetime.now(),
    )


def build_relic_active_status_embed(
    _channel: discord.abc.Messageable | None,
    timer: RelicTimer,
    *,
    title: str = "⏳ Таймер Реликвии активен",
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        color=discord.Color.green(),
        timestamp=datetime.now(),
    )
    embed.add_field(
        name="📢 Уведомление",
        value=notification_field_value(),
        inline=False,
    )
    if timer.timer_start_time and timer.timer_duration:
        appear_time = timer.timer_start_time + timedelta(
            minutes=timer.timer_duration
        )
        unix_timestamp = appear_unix_timestamp_at(appear_time)
        embed.add_field(
            name="⏰ Время появления",
            value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
            inline=True,
        )
    if timer.started_by:
        embed.set_footer(text=f"Запустил: {timer.started_by}")
    return embed


def build_relic_inactive_embed(
    *,
    title: str = "❌ Таймер Реликвии не активен",
    hint: str = "Нажмите «Запустить» на панели или используйте `/relic start`",
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description="Нет запущенного таймера Реликвии.",
        color=discord.Color.red(),
    )
    embed.add_field(
        name="💡 Запустить таймер Реликвии",
        value=hint,
        inline=False,
    )
    return embed


def build_relic_completed_hold_embed(timer: RelicTimer) -> discord.Embed:
    """Панель после появления: таймер ещё виден RELIC_PANEL_HOLD_MINUTES."""
    embed = discord.Embed(
        title="⚔️ Таймер Реликвии",
        description="Реликвия появилась.",
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )
    if timer.timer_start_time and timer.timer_duration:
        appear_time = timer.timer_start_time + timedelta(
            minutes=timer.timer_duration
        )
        unix_timestamp = appear_unix_timestamp_at(appear_time)
        embed.add_field(
            name="⏰ Время появления",
            value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
            inline=False,
        )
    hold_until = getattr(timer, "_hold_until", None)
    if hold_until is not None:
        hold_unix = appear_unix_timestamp_at(hold_until)
        embed.add_field(
            name="🧹 Сброс панели",
            value=f"<t:{hold_unix}:R>",
            inline=False,
        )
    if timer.started_by:
        embed.set_footer(text=f"Запустил: {timer.started_by}")
    return embed


def build_relic_panel_embed(timer: RelicTimer) -> discord.Embed:
    """Embed постоянного сообщения панели реликвии."""
    if timer.is_holding():
        return build_relic_completed_hold_embed(timer)

    if not timer.is_active():
        return build_relic_inactive_embed(
            title="⚔️ Таймер Реликвии",
            hint="Нажмите «Запустить», чтобы задать время до появления",
        )

    remaining = timer.get_remaining_time()
    warning_sec = config.RELIC_WARNING_MINUTES * 60
    if remaining is not None and remaining <= warning_sec:
        color = discord.Color.yellow()
    else:
        color = discord.Color.green()

    embed = build_relic_active_status_embed(
        None,
        timer,
        title="⚔️ Таймер Реликвии",
    )
    embed.color = color
    return embed