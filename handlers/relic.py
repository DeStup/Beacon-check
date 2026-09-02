"""Slash-команды таймера реликвии."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ui import Button, View

import config
from utils.autocomplete import get_minute_options
from utils.formatting import format_duration_minutes, get_user_info
from utils.logging_setup import action_logger, error_logger

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    @bot.tree.command(
        name="relic",
        description=(
            "Запустить таймер до появления реликвии (по умолчанию 90 минут)"
        ),
    )
    @app_commands.describe(
        minutes="Время до появления реликвии в минутах (по умолчанию 90)"
    )
    @app_commands.autocomplete(minutes=get_minute_options)
    async def relic(
        interaction: discord.Interaction,
        minutes: Optional[int] = None,
    ) -> None:
        user_info = get_user_info(interaction)
        timer = bot.relic_timer

        if config.RELIC_CHANNEL_ID == 0:
            await interaction.response.send_message(
                "❌ Канал для реликвий не настроен! "
                "Добавьте RELIC_CHANNEL_ID в .env файл.",
                ephemeral=True,
            )
            error_logger.error(
                f"{user_info} tried to use /relic but RELIC_CHANNEL_ID "
                "is not configured"
            )
            return

        relic_channel = bot.get_channel(config.RELIC_CHANNEL_ID)
        if not relic_channel:
            await interaction.response.send_message(
                f"❌ Канал с ID {config.RELIC_CHANNEL_ID} не найден! "
                "Проверьте настройки.",
                ephemeral=True,
            )
            error_logger.error(
                f"{user_info} tried to use /relic but channel "
                f"{config.RELIC_CHANNEL_ID} not found"
            )
            return

        if minutes is None:
            minutes = config.DEFAULT_RELIC_MINUTES
        elif minutes < 1:
            await interaction.response.send_message(
                "❌ Время должно быть больше 0 минут!",
                ephemeral=True,
            )
            return
        elif minutes > config.MAX_RELIC_MINUTES:
            await interaction.response.send_message(
                f"❌ Время не должно превышать {config.MAX_RELIC_MINUTES} минут "
                "(24 часа)!",
                ephemeral=True,
            )
            return

        if timer.is_active():
            class TimerManageView(View):
                def __init__(self) -> None:
                    super().__init__(timeout=30)

                @discord.ui.button(
                    label="Отменить таймер",
                    style=discord.ButtonStyle.danger,
                    emoji="⏹️",
                )
                async def cancel_timer_button(
                    self,
                    btn_interaction: discord.Interaction,
                    button: Button,
                ) -> None:
                    if btn_interaction.user.id != interaction.user.id:
                        await btn_interaction.response.send_message(
                            "❌ Вы не можете управлять этим таймером!",
                            ephemeral=True,
                        )
                        return

                    if timer.cancel_timer():
                        embed = discord.Embed(
                            title="⏹️ Таймер отменен",
                            description="Таймер появления реликвии был отменен.",
                            color=discord.Color.red(),
                            timestamp=datetime.now(),
                        )
                        await btn_interaction.response.edit_message(
                            embed=embed,
                            view=None,
                        )
                        action_logger.info(
                            f"{get_user_info(btn_interaction)} cancelled relic timer"
                        )
                    else:
                        await btn_interaction.response.edit_message(
                            content="❌ Таймер не найден или уже завершен.",
                            view=None,
                        )

                @discord.ui.button(
                    label="Перезапустить",
                    style=discord.ButtonStyle.primary,
                    emoji="🔄",
                )
                async def restart_timer_button(
                    self,
                    btn_interaction: discord.Interaction,
                    button: Button,
                ) -> None:
                    if btn_interaction.user.id != interaction.user.id:
                        await btn_interaction.response.send_message(
                            "❌ Вы не можете управлять этим таймером!",
                            ephemeral=True,
                        )
                        return

                    timer.cancel_timer()
                    await timer.start_timer(bot, minutes)
                    time_str = format_duration_minutes(minutes)
                    unix_timestamp = int(
                        (datetime.now() + timedelta(minutes=minutes)).timestamp()
                    )

                    embed = discord.Embed(
                        title="🔄 Таймер перезапущен",
                        description=(
                            f"Таймер появления реликвии перезапущен на **{time_str}**"
                        ),
                        color=discord.Color.blue(),
                        timestamp=datetime.now(),
                    )
                    embed.add_field(
                        name="⏰ Время появления",
                        value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
                        inline=True,
                    )
                    embed.add_field(
                        name="📢 Уведомление",
                        value=(
                            "За 10 минут до появления будет отправлено предупреждение"
                        ),
                        inline=False,
                    )
                    embed.add_field(
                        name="📌 Канал",
                        value=relic_channel.mention,
                        inline=False,
                    )
                    await btn_interaction.response.edit_message(
                        embed=embed,
                        view=None,
                    )
                    action_logger.info(
                        f"{get_user_info(btn_interaction)} restarted relic timer "
                        f"for {minutes} minutes"
                    )

            embed = discord.Embed(
                title="⏳ Таймер уже запущен",
                description=(
                    f"В канале {relic_channel.mention} уже запущен "
                    "таймер появления реликвии."
                ),
                color=discord.Color.orange(),
            )
            embed.add_field(
                name="🔄 Что делать?",
                value=(
                    "Вы можете отменить текущий таймер или перезапустить "
                    "его с новым временем."
                ),
                inline=False,
            )
            await interaction.response.send_message(
                embed=embed,
                view=TimerManageView(),
                ephemeral=True,
            )
            return

        await timer.start_timer(bot, minutes)
        time_str = format_duration_minutes(minutes)
        unix_timestamp = int(
            (datetime.now() + timedelta(minutes=minutes)).timestamp()
        )

        embed = discord.Embed(
            title="⏳ Таймер реликвии запущен",
            description=f"Реликвия появится через **{time_str}**",
            color=discord.Color.gold(),
            timestamp=datetime.now(),
        )
        embed.add_field(
            name="📢 Уведомление",
            value="За 10 минут до появления будет отправлено предупреждение",
            inline=False,
        )
        embed.add_field(
            name="⏰ Время появления",
            value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
            inline=True,
        )
        embed.add_field(
            name="📌 Канал",
            value=relic_channel.mention,
            inline=True,
        )
        embed.add_field(name="📊 Статус", value="🟢 Активен", inline=True)
        embed.set_footer(text=f"Запустил: {interaction.user.name}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="relic_cancel",
        description="Отменить запущенный таймер реликвии",
    )
    async def relic_cancel(interaction: discord.Interaction) -> None:
        user_info = get_user_info(interaction)
        if config.RELIC_CHANNEL_ID == 0:
            await interaction.response.send_message(
                "❌ Канал для реликвий не настроен!",
                ephemeral=True,
            )
            return

        if bot.relic_timer.cancel_timer():
            embed = discord.Embed(
                title="⏹️ Таймер отменен",
                description="Таймер появления реликвии был успешно отменен.",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            action_logger.info(f"{user_info} cancelled relic timer")
        else:
            await interaction.response.send_message(
                "❌ Нет активного таймера реликвии.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="relic_status",
        description="Показать статус таймера реликвии",
    )
    async def relic_status(interaction: discord.Interaction) -> None:
        if config.RELIC_CHANNEL_ID == 0:
            await interaction.response.send_message(
                "❌ Канал для реликвий не настроен!",
                ephemeral=True,
            )
            return

        relic_channel = bot.get_channel(config.RELIC_CHANNEL_ID)
        if not relic_channel:
            await interaction.response.send_message(
                f"❌ Канал с ID {config.RELIC_CHANNEL_ID} не найден!",
                ephemeral=True,
            )
            return

        timer = bot.relic_timer
        if timer.is_active():
            embed = discord.Embed(
                title="⏳ Таймер реликвии активен",
                description=(
                    f"В канале {relic_channel.mention} запущен "
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
                value="За 10 минут до появления будет отправлено предупреждение",
                inline=True,
            )
            embed.add_field(
                name="📌 Канал",
                value=relic_channel.mention,
                inline=True,
            )
            if timer.timer_start_time and timer.timer_duration:
                appear_time = timer.timer_start_time + timedelta(
                    minutes=timer.timer_duration
                )
                unix_timestamp = int(appear_time.timestamp())
                embed.add_field(
                    name="⏰ Примерное время появления",
                    value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
                    inline=False,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="❌ Таймер не активен",
                description="Нет запущенного таймера реликвии.",
                color=discord.Color.red(),
            )
            embed.add_field(
                name="💡 Запустить таймер",
                value="Используйте команду `/relic` для запуска таймера",
                inline=False,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
