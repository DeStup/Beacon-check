"""Меню управления маяками."""

from __future__ import annotations

import discord
from discord.ui import Button, View

from handlers.views.clear import ConfirmClearView
from handlers.views.select import BeaconSelectView
from services import database as db
from utils.permissions import can_clear_beacons


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
    if db.count_beacons() == 0:
        await interaction.response.send_message(empty_message, ephemeral=True)
        return

    embed = discord.Embed(title=title, description=description, color=color)
    view = BeaconSelectView(action, interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class BeaconMenuView(View):
    """Кнопочное меню управления маяками."""

    def __init__(self) -> None:
        super().__init__(timeout=120)

    @discord.ui.button(
        label="Добавить маяк",
        style=discord.ButtonStyle.green,
        emoji="➕",
        row=0,
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.send_message(
            "Используйте команду `/add` для добавления маяка:\n",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Заправить",
        style=discord.ButtonStyle.primary,
        emoji="⛽",
        row=0,
    )
    async def refuel_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_beacon_select(
            interaction,
            action="refuel",
            title="⛽ Заправка маяка",
            description="Выберите маяк из списка ниже:",
            empty_message="❌ Нет активных маяков для заправки!",
        )

    @discord.ui.button(
        label="Статус",
        style=discord.ButtonStyle.secondary,
        emoji="📊",
        row=0,
    )
    async def status_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_beacon_select(
            interaction,
            action="status",
            title="📊 Просмотр статуса маяка",
            description=(
                "Выберите маяк для просмотра детального статуса\n"
                "или выберите 'Показать все маяки' для общего обзора"
            ),
            empty_message="📭 Нет активных маяков",
        )

    @discord.ui.button(
        label="Редактировать",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        row=1,
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
        label="Обновить",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        row=1,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        embed = discord.Embed(
            title="🔄 Данные обновлены",
            description="Последнее обновление выполнено",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Очистить всё",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        row=2,
    )
    async def clear_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        if not can_clear_beacons(interaction.user):
            embed = discord.Embed(
                title="❌ Доступ запрещен",
                description="У вас нет прав для выполнения этой команды!",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="⚠️ Подтверждение действия",
            description=(
                "Вы уверены, что хотите удалить **ВСЕ** маяки?\n"
                "Это действие нельзя отменить!"
            ),
            color=discord.Color.yellow(),
        )
        embed.set_footer(text="У вас есть 30 секунд на подтверждение")
        view = ConfirmClearView(interaction.user, interaction)
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )
