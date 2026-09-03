"""Slash-команды таймера реликвии."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ui import Button, Modal, TextInput, View

import config
from utils.autocomplete import get_minute_options
from utils.formatting import get_user_info
from utils.logging_setup import relic_logger
from utils.relic_embeds import (
    build_relic_active_status_embed,
    build_relic_already_running_embed,
    build_relic_cancelled_embed,
    build_relic_inactive_embed,
    build_relic_restarted_embed,
    build_relic_started_embed,
    ensure_relic_channel,
)

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    relic = app_commands.Group(
        name="relic",
        description="Таймер появления реликвии",
    )

    @relic.command(
        name="start",
        description=(
            "Запустить таймер до появления реликвии (по умолчанию 90 минут)"
        ),
    )
    @app_commands.describe(
        minutes="Время до появления реликвии в минутах (по умолчанию 90)"
    )
    @app_commands.autocomplete(minutes=get_minute_options)
    async def start(
        interaction: discord.Interaction,
        minutes: Optional[int] = None,
    ) -> None:
        user_info = get_user_info(interaction)
        timer = bot.relic_timer

        relic_channel = await ensure_relic_channel(
            interaction,
            bot,
            user_info=user_info,
            log_context="/relic start",
        )
        if relic_channel is None:
            return

        if minutes is not None:
            if minutes < 1:
                await interaction.response.send_message(
                    "❌ Время должно быть больше 0 минут!",
                    ephemeral=True,
                )
                return
            if minutes > config.MAX_RELIC_MINUTES:
                await interaction.response.send_message(
                    f"❌ Время не должно превышать {config.MAX_RELIC_MINUTES} минут "
                    "(24 часа)!",
                    ephemeral=True,
                )
                return

        if timer.is_active():
            class RestartMinutesModal(Modal, title="🔄 Перезапуск таймера"):
                minutes_input = TextInput(
                    label="Минуты до появления реликвии",
                    placeholder=f"1–{config.MAX_RELIC_MINUTES}, например 90",
                    required=True,
                    min_length=1,
                    max_length=4,
                    default=(
                        str(minutes)
                        if minutes is not None
                        else str(config.DEFAULT_RELIC_MINUTES)
                    ),
                )

                async def on_submit(
                    self, modal_interaction: discord.Interaction
                ) -> None:
                    if modal_interaction.user.id != interaction.user.id:
                        await modal_interaction.response.send_message(
                            "❌ Вы не можете управлять этим таймером!",
                            ephemeral=True,
                        )
                        return

                    raw = self.minutes_input.value.strip()
                    try:
                        new_minutes = int(raw)
                    except ValueError:
                        await modal_interaction.response.send_message(
                            "❌ Введите целое число минут!",
                            ephemeral=True,
                        )
                        return

                    if new_minutes < 1:
                        await modal_interaction.response.send_message(
                            "❌ Время должно быть больше 0 минут!",
                            ephemeral=True,
                        )
                        return
                    if new_minutes > config.MAX_RELIC_MINUTES:
                        await modal_interaction.response.send_message(
                            f"❌ Время не должно превышать "
                            f"{config.MAX_RELIC_MINUTES} минут (24 часа)!",
                            ephemeral=True,
                        )
                        return

                    await _restart_timer(
                        modal_interaction,
                        new_minutes=new_minutes,
                    )

            class TimerManageView(View):
                def __init__(self) -> None:
                    super().__init__(timeout=60)

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
                    await btn_interaction.response.send_modal(RestartMinutesModal())

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

                    if timer.cancel_timer(
                        user_info=get_user_info(btn_interaction),
                    ):
                        await btn_interaction.response.edit_message(
                            embed=build_relic_cancelled_embed(),
                            view=None,
                        )
                    else:
                        await btn_interaction.response.edit_message(
                            content="❌ Таймер не найден или уже завершен.",
                            embed=None,
                            view=None,
                        )

            async def _restart_timer(
                ui_interaction: discord.Interaction,
                *,
                new_minutes: int,
            ) -> None:
                ui_user = get_user_info(ui_interaction)
                timer.cancel_timer(log=False)
                await timer.start_timer(
                    bot,
                    new_minutes,
                    user_info=ui_user,
                    started_by=ui_interaction.user.name,
                    restarted=True,
                )
                await ui_interaction.response.edit_message(
                    embed=build_relic_restarted_embed(relic_channel, new_minutes),
                    view=None,
                )

            await interaction.response.send_message(
                embed=build_relic_already_running_embed(relic_channel, timer),
                view=TimerManageView(),
                ephemeral=True,
            )
            return

        if minutes is None:
            minutes = config.DEFAULT_RELIC_MINUTES

        await timer.start_timer(
            bot,
            minutes,
            user_info=user_info,
            started_by=interaction.user.name,
        )
        embed = build_relic_started_embed(
            relic_channel,
            minutes,
            started_by=interaction.user.name,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @relic.command(
        name="cancel",
        description="Отменить запущенный таймер реликвии",
    )
    async def cancel(interaction: discord.Interaction) -> None:
        user_info = get_user_info(interaction)
        if config.RELIC_CHANNEL_ID == 0:
            await interaction.response.send_message(
                "❌ Канал для реликвий не настроен!",
                ephemeral=True,
            )
            return

        if bot.relic_timer.cancel_timer(user_info=user_info):
            embed = build_relic_cancelled_embed(
                "Таймер появления реликвии был успешно отменен."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Нет активного таймера реликвии.",
                ephemeral=True,
            )

    @relic.command(
        name="status",
        description="Показать статус таймера реликвии",
    )
    async def status(interaction: discord.Interaction) -> None:
        user_info = get_user_info(interaction)
        relic_channel = await ensure_relic_channel(
            interaction,
            bot,
            user_info=user_info,
            log_context="/relic status",
        )
        if relic_channel is None:
            return

        timer = bot.relic_timer
        active = timer.is_active()
        relic_logger.info(
            f"{user_info} checked relic timer status "
            f"(active={active})"
        )
        if active:
            embed = build_relic_active_status_embed(relic_channel, timer)
        else:
            embed = build_relic_inactive_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(relic)
