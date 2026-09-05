"""Меню и постоянная панель управления маяками."""

from __future__ import annotations

import discord
from discord.ui import Button, View

from handlers.views.clear import prompt_clear_all_beacons
from handlers.views.select import BeaconSelectView
from services import database as db
from services.beacon_service import (
    apply_decay_to_all_beacons,
    build_all_beacons_status_embed,
    refresh_beacon_panel,
)
from utils.formatting import get_user_info
from utils.logging_setup import action_logger


async def open_beacon_select(
    interaction: discord.Interaction,
    *,
    action: str,
    title: str,
    description: str,
    empty_message: str,
    color: discord.Color = discord.Color.blue(),
) -> None:
    """Общий хелпер: выбор маяка или сообщение об отсутствии."""
    beacons = db.list_beacons_summary()
    if not beacons:
        await interaction.response.send_message(empty_message, ephemeral=True)
        return

    embed = discord.Embed(title=title, description=description, color=color)
    view = BeaconSelectView(action, interaction.user.id, beacons)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class BeaconPanelView(View):
    """Постоянное меню «Панель Маяков»."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Добавить",
        style=discord.ButtonStyle.green,
        emoji="➕",
        row=0,
        custom_id="beacon_panel:add",
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.send_message(
            "Используйте команду `/beacon add` для добавления маяка.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Обновить",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        row=0,
        custom_id="beacon_panel:refresh",
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        updated = apply_decay_to_all_beacons()
        action_logger.info(
            f"{get_user_info(interaction)} refreshed beacon panel "
            f"({updated} beacons updated)"
        )
        await interaction.response.edit_message(
            embed=build_all_beacons_status_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Редактировать",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        row=0,
        custom_id="beacon_panel:edit",
    )
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_beacon_select(
            interaction,
            action="edit",
            title="✏️ Редактирование маяка",
            description="Выберите маяк из списка ниже:",
            empty_message="❌ Нет активных маяков для редактирования!",
        )

    @discord.ui.button(
        label="Удалить",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        row=1,
        custom_id="beacon_panel:delete",
    )
    async def delete_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_beacon_select(
            interaction,
            action="delete",
            title="🗑️ Удаление маяка",
            description="Выберите маяк из списка ниже:",
            empty_message="❌ Нет активных маяков для удаления!",
            color=discord.Color.red(),
        )

    @discord.ui.button(
        label="Очистить всё",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        row=1,
        custom_id="beacon_panel:clear",
    )
    async def clear_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await prompt_clear_all_beacons(interaction)
