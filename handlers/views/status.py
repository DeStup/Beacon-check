"""Отображение статуса маяков."""

from __future__ import annotations

from datetime import datetime

import discord

import config
from services import database as db
from utils.embeds import progress_bar
from utils.formatting import format_priority, get_user_info
from utils.logging_setup import action_logger, error_logger


async def show_beacon_status(
    interaction: discord.Interaction,
    beacon_id: str,
) -> None:
    """Показать статус конкретного маяка."""
    user_info = get_user_info(interaction)
    try:
        beacon = db.get_beacon(beacon_id)
        if not beacon:
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} не найден!",
                ephemeral=True,
            )
            return

        action_logger.info(f"{user_info} checked status of beacon {beacon_id}")

        hours_remaining_fuel = (
            beacon["current_fuel"] * beacon["fuel_consumption_rate"]
        )
        hours_remaining_lifetime = (
            beacon["current_lifetime"] / config.LIFETIME_DECAY_RATE
        )
        priority_text = format_priority(
            float(beacon["fuel_consumption_rate"]),
            with_number=True,
        )

        if beacon["current_lifetime"] <= config.CRITICAL_THRESHOLD:
            status_msg = "💀 КРИТИЧЕСКИЙ УРОВЕНЬ - скоро сгниет!"
        else:
            status_msg = f"⏳ осталось ~{hours_remaining_lifetime:.1f} часов"

        embed = discord.Embed(
            title=f"📊 Статус маяка {beacon['beacon_id']}",
            description=f"Запросил: {interaction.user.mention}",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )
        embed.add_field(
            name="🔋 Топливо",
            value=f"~{beacon['current_fuel']:.0f} (⏳ ~{hours_remaining_fuel:.1f} ч)",
            inline=True,
        )
        embed.add_field(
            name="🔄 Прочность",
            value=f"{beacon['current_lifetime']:.2f}%\n{status_msg}",
            inline=True,
        )
        embed.add_field(name="Тип", value=priority_text, inline=True)
        embed.add_field(
            name="📊 Детально",
            value=(
                f"🔋 {progress_bar(beacon['current_fuel'], config.MAX_FUEL)} "
                f"{beacon['current_fuel']:.1f}/{config.MAX_FUEL}\n"
                f"🔄 {progress_bar(beacon['current_lifetime'], config.MAX_LIFETIME)} "
                f"{beacon['current_lifetime']:.1f}%"
            ),
            inline=False,
        )
        if beacon["message_link"]:
            embed.add_field(
                name="",
                value=f"🔗[Перейти]({beacon['message_link']})",
                inline=False,
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    except Exception as exc:
        error_logger.error(
            f"{user_info} Ошибка при просмотре статуса: {exc}",
            exc_info=True,
        )
        await interaction.response.send_message(
            f"❌ Ошибка: {exc}",
            ephemeral=True,
        )


async def show_all_beacons_status(interaction: discord.Interaction) -> None:
    """Показать статус всех маяков (лично)."""
    user_info = get_user_info(interaction)
    try:
        beacons = db.list_all_beacons()
        if not beacons:
            action_logger.info(f"{user_info} checked status - no active beacons")
            await interaction.response.send_message(
                "📭 Нет активных маяков",
                ephemeral=True,
            )
            return

        action_logger.info(
            f"{user_info} requested public status of all beacons "
            f"({len(beacons)} active)"
        )

        embed = discord.Embed(
            title="📊 Статус всех маяков",
            description=f"Запросил: {interaction.user.mention}",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        for beacon in beacons:
            fuel_percent = (beacon["current_fuel"] / config.MAX_FUEL) * 100
            # Сохраняем исходный порядок проверок (сначала 20%, затем 5%)
            status_mark = ""
            if (
                beacon["current_lifetime"] <= config.WARNING_THRESHOLD
                or fuel_percent <= config.WARNING_THRESHOLD
            ):
                status_mark = "⚠️ "
            elif (
                beacon["current_lifetime"] <= config.CRITICAL_THRESHOLD
                or fuel_percent <= config.CRITICAL_THRESHOLD
            ):
                status_mark = "💀 "

            field_value = (
                f"🔋 {progress_bar(beacon['current_fuel'], config.MAX_FUEL)} "
                f"{beacon['current_fuel']:.1f}/{config.MAX_FUEL}\n"
                f"🔄 {progress_bar(beacon['current_lifetime'], config.MAX_LIFETIME)} "
                f"{beacon['current_lifetime']:.1f}%"
            )
            if beacon["message_link"]:
                field_value += f"\n[Перейти]({beacon['message_link']})"

            type_label = format_priority(
                float(beacon["fuel_consumption_rate"])
            )
            embed.add_field(
                name=f"{status_mark}{beacon['beacon_id']} · {type_label}",
                value=field_value,
                inline=False,
            )

        embed.set_footer(
            text="Фронтовой | Тыловой | ⚠️ Требует внимания"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    except Exception as exc:
        error_logger.error(
            f"{user_info} Ошибка при просмотре статуса: {exc}",
            exc_info=True,
        )
        await interaction.response.send_message(
            f"❌ Ошибка: {exc}",
            ephemeral=True,
        )
