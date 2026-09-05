"""Постоянная панель реликвии и связанные UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import Button, Modal, TextInput, View

import config
from utils.formatting import get_user_info

if TYPE_CHECKING:
    from bot import BeaconBot


class RelicMinutesModal(Modal):
    """Модалка минут для запуска / перезапуска с панели."""

    def __init__(self, *, restarted: bool) -> None:
        title = (
            "🔄 Перезапуск таймера"
            if restarted
            else "▶️ Запуск таймера"
        )
        super().__init__(title=title)
        self.restarted = restarted
        self.minutes_input = TextInput(
            label="Минуты до появления реликвии",
            placeholder=f"1–{config.MAX_RELIC_MINUTES}, например 90",
            required=True,
            min_length=1,
            max_length=4,
            default=str(config.DEFAULT_RELIC_MINUTES),
        )
        self.add_item(self.minutes_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: BeaconBot = interaction.client  # type: ignore[assignment]
        raw = self.minutes_input.value.strip()
        try:
            minutes = int(raw)
        except ValueError:
            await interaction.response.send_message(
                "❌ Введите целое число минут!",
                ephemeral=True,
            )
            return

        if minutes < 1:
            await interaction.response.send_message(
                "❌ Время должно быть больше 0 минут!",
                ephemeral=True,
            )
            return
        if minutes > config.MAX_RELIC_MINUTES:
            await interaction.response.send_message(
                f"❌ Время не должно превышать "
                f"{config.MAX_RELIC_MINUTES} минут (24 часа)!",
                ephemeral=True,
            )
            return

        timer = bot.relic_timer
        if self.restarted:
            timer.cancel_timer(log=False)

        await timer.start_timer(
            bot,
            minutes,
            user_info=get_user_info(interaction),
            started_by=interaction.user.name,
            restarted=self.restarted,
        )
        action = "перезапущен" if self.restarted else "запущен"
        await interaction.response.send_message(
            f"✅ Таймер реликвии {action} на **{minutes}** мин.",
            ephemeral=True,
        )


class RelicPanelIdleView(View):
    """Панель без активного таймера — только запуск."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Запустить",
        style=discord.ButtonStyle.green,
        emoji="▶️",
        custom_id="relic_panel:start",
    )
    async def start_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.send_modal(
            RelicMinutesModal(restarted=False)
        )


class RelicPanelActiveView(View):
    """Панель с активным таймером — перезапуск и отмена."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Перезапустить",
        style=discord.ButtonStyle.primary,
        emoji="🔄",
        custom_id="relic_panel:restart",
    )
    async def restart_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.send_modal(
            RelicMinutesModal(restarted=True)
        )

    @discord.ui.button(
        label="Отменить",
        style=discord.ButtonStyle.danger,
        emoji="⏹️",
        custom_id="relic_panel:cancel",
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        from services.relic_service import refresh_relic_panel

        bot: BeaconBot = interaction.client  # type: ignore[assignment]
        if bot.relic_timer.cancel_timer(
            user_info=get_user_info(interaction),
        ):
            await interaction.response.send_message(
                "✅ Таймер реликвии отменён.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ Нет активного таймера реликвии.",
                ephemeral=True,
            )
        await refresh_relic_panel(bot)


def relic_panel_view_for(timer_active: bool) -> View:
    if timer_active:
        return RelicPanelActiveView()
    return RelicPanelIdleView()
