"""Меню, select, статус и очистка upkeep."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

import discord
from discord.ui import Button, Select, View

import config
from handlers.views.upkeep_modals import (
    AddUpkeepModal,
    DeleteUpkeepModal,
    EditUpkeepModal,
)
from services import database as db
from services.database import Row
from services.upkeep_service import (
    apply_decay_to_all_upkeep,
    build_all_upkeep_status_embed,
    build_upkeep_status_embed,
    display_silver_amount,
    refresh_upkeep_panel,
    snapshot_upkeep,
)
from utils.formatting import (
    delete_select_message,
    format_duration_hours,
    get_user_info,
)
from utils.logging_setup import error_logger, upkeep_logger
from utils.permissions import can_delete_owned, can_manage_upkeep


def _notice_embed(
    description: str,
    *,
    title: str = "❌ Ошибка",
    color: discord.Color = discord.Color.red(),
) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


async def _sync_panel(interaction: discord.Interaction) -> None:
    bot = interaction.client
    await refresh_upkeep_panel(bot)  # type: ignore[arg-type]


async def open_upkeep_select(
    interaction: discord.Interaction,
    *,
    action: str,
    title: str,
    description: str,
    empty_message: str,
    color: discord.Color = discord.Color.blue(),
) -> None:
    rows = db.list_upkeep_summary()
    if action == "delete" and not can_manage_upkeep(interaction.user):
        rows = [
            row
            for row in rows
            if can_delete_owned(interaction.user, row["created_by"])
        ]
    if not rows:
        await interaction.response.send_message(
            embed=_notice_embed(
                empty_message,
                title="📭 Пусто",
                color=discord.Color.orange(),
            ),
            ephemeral=True,
        )
        return

    embed = discord.Embed(title=title, description=description, color=color)
    view = UpkeepSelectView(action, interaction.user.id, rows, interaction)
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=True
    )


async def show_upkeep_status(
    interaction: discord.Interaction,
    name: str,
) -> None:
    row = db.get_upkeep_by_name(name)
    if not row:
        await interaction.response.send_message(
            embed=_notice_embed(f"Объект **{name}** не найден!"),
            ephemeral=True,
        )
        return

    snap = snapshot_upkeep(row)
    db.update_upkeep(
        snap["id"],
        silver_amount=snap["silver_amount"],
        last_updated=datetime.now().isoformat(),
    )
    color = discord.Color.green()
    if snap["hours_left"] <= 0:
        color = discord.Color.red()
    elif snap["hours_left"] < config.UPKEEP_WARNING_HOURS:
        color = discord.Color.orange()

    embed = build_upkeep_status_embed(
        title="📊 Статус содержания",
        name=snap["name"],
        silver_amount=snap["silver_amount"],
        silver_per_hour=snap["silver_per_hour"],
        hours_left=snap["hours_left"],
        color=color,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def show_all_upkeep_status(
    interaction: discord.Interaction,
) -> None:
    if not config.PANEL_CHANNEL_ID:
        await interaction.response.send_message(
            embed=_notice_embed(
                "Канал панели не настроен (`PANEL_CHANNEL_ID`).",
            ),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    apply_decay_to_all_upkeep()
    message = await refresh_upkeep_panel(interaction.client)  # type: ignore[arg-type]
    if message is None:
        await interaction.followup.send(
            embed=_notice_embed(
                "Не удалось обновить панель Владений Новгорода. "
                "Проверьте канал и права бота."
            ),
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        embed=discord.Embed(
            title="Панель Владений Новгорода",
            description=f"Панель обновлена: {message.jump_url}",
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


def build_upkeep_clear_confirm_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚠️ Подтверждение действия",
        description=(
            "Вы уверены, что хотите удалить **ВСЕ** объекты содержания?\n"
            "Это действие нельзя отменить!"
        ),
        color=discord.Color.yellow(),
    )
    embed.set_footer(text="У вас есть 30 секунд на подтверждение")
    return embed


async def prompt_clear_all_upkeep(
    interaction: discord.Interaction,
    *,
    yes_label: str = "Да, удалить всё",
    no_label: str = "Нет, отмена",
    slash_button_styles: bool = False,
) -> None:
    if not can_manage_upkeep(interaction.user):
        embed = discord.Embed(
            title="❌ Доступ запрещен",
            description="У вас нет прав для выполнения этой команды!",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = ConfirmClearUpkeepView(
        interaction.user,
        interaction,
        yes_label=yes_label,
        no_label=no_label,
    )
    if slash_button_styles:
        for child in view.children:
            if isinstance(child, Button):
                if child.label == "Да":
                    child.style = discord.ButtonStyle.green
                elif child.label == "Нет":
                    child.style = discord.ButtonStyle.red

    await interaction.response.send_message(
        embed=build_upkeep_clear_confirm_embed(),
        view=view,
        ephemeral=True,
    )


class ConfirmClearUpkeepView(View):
    def __init__(
        self,
        original_user: discord.abc.User,
        original_interaction: discord.Interaction,
        *,
        yes_label: str = "Да, удалить всё",
        no_label: str = "Нет, отмена",
    ) -> None:
        super().__init__(timeout=30)
        self.original_user = original_user
        self.original_interaction = original_interaction

        yes = Button(label=yes_label, style=discord.ButtonStyle.danger, emoji="✅")
        yes.callback = self._confirm
        self.add_item(yes)

        no = Button(label=no_label, style=discord.ButtonStyle.secondary, emoji="❌")
        no.callback = self._cancel
        self.add_item(no)

    async def _confirm(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message(
                embed=_notice_embed("Вы не можете подтвердить чужую команду!"),
                ephemeral=True,
            )
            return
        try:
            names = db.clear_all_upkeep()
            count = len(names)
            if count > 0:
                upkeep_logger.info(
                    f"{get_user_info(interaction)} cleared ALL upkeep | "
                    f"Deleted: {count}: {', '.join(names)}"
                )
            embed = discord.Embed(
                title="🧹 Очистка содержания",
                description=f"**Удалено объектов: {count}**",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            if count > 0:
                preview = ", ".join(names[:10])
                if len(names) > 10:
                    preview += f" и еще {len(names) - 10}"
                embed.add_field(
                    name="📋 Удалённые объекты",
                    value=preview,
                    inline=False,
                )
            await interaction.response.edit_message(
                content=None,
                embed=embed,
                view=None,
            )
            await _sync_panel(interaction)
        except Exception as exc:
            error_logger.error(
                f"{get_user_info(interaction)} upkeep clear failed: {exc}",
                exc_info=True,
            )
            await interaction.response.edit_message(
                content=None,
                embed=_notice_embed(f"Ошибка при удалении: {exc}"),
                view=None,
            )

    async def _cancel(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message(
                embed=_notice_embed("Вы не можете отменить чужую команду!"),
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            content=None,
            embed=discord.Embed(
                title="❌ Отменено",
                description="Очистка содержания отменена.",
                color=discord.Color.orange(),
            ),
            view=None,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        try:
            await self.original_interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title="⌛ Время истекло",
                    description="Очистка отменена.",
                    color=discord.Color.orange(),
                ),
                view=self,
            )
        except discord.HTTPException:
            pass


class UpkeepSelectView(View):
    def __init__(
        self,
        action_type: str,
        user_id: int,
        rows: Sequence[Row],
        source_interaction: discord.Interaction,
    ) -> None:
        super().__init__(timeout=60)
        self.action_type = action_type
        self.user_id = user_id
        self.source_interaction = source_interaction
        self.add_item(UpkeepSelect(action_type, rows))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=_notice_embed("Вы не можете использовать это меню!"),
                ephemeral=True,
            )
            return False
        return True


class UpkeepSelect(Select):
    def __init__(self, action_type: str, rows: Sequence[Row]) -> None:
        self.action_type = action_type
        options: list[discord.SelectOption] = []
        if action_type == "status":
            options.append(
                discord.SelectOption(
                    label="📊 Показать все",
                    value="all",
                    description="Статус всех объектов содержания",
                    emoji="📋",
                )
            )
        for row in rows[:24]:
            snap = snapshot_upkeep(row)
            stock = display_silver_amount(snap["silver_amount"])
            if stock == 0:
                left = "гниёт"
            elif snap["hours_left"] == float("inf"):
                left = "∞"
            else:
                left = format_duration_hours(snap["hours_left"])
            options.append(
                discord.SelectOption(
                    label=snap["name"][:100],
                    value=snap["name"],
                    description=(
                        f"{stock} серебра · {left}"
                    )[:100],
                    emoji="🪙",
                )
            )
        if not options:
            options = [
                discord.SelectOption(
                    label="Нет объектов",
                    value="none",
                    emoji="⚠️",
                )
            ]
        super().__init__(
            placeholder="🔍 Выберите объект...",
            min_values=1,
            max_values=1,
            options=options,
        )

    def _source(self) -> discord.Interaction | None:
        view = self.view
        if isinstance(view, UpkeepSelectView):
            return view.source_interaction
        return None

    async def callback(self, interaction: discord.Interaction) -> None:
        source = self._source()
        value = self.values[0]
        if value == "none":
            await interaction.response.send_message(
                embed=_notice_embed(
                    "Нет объектов содержания.",
                    title="📭 Пусто",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            if source is not None:
                await delete_select_message(source)
            return

        if self.action_type == "status":
            if value == "all":
                await show_all_upkeep_status(interaction)
            else:
                await show_upkeep_status(interaction, value)
            if source is not None:
                await delete_select_message(source)
            return

        if self.action_type == "edit":
            await interaction.response.send_modal(EditUpkeepModal(value))
            if source is not None:
                await delete_select_message(source)
            return
        if self.action_type == "delete":
            row = db.get_upkeep_by_name(value)
            if not row:
                await interaction.response.send_message(
                    embed=_notice_embed(f"Объект **{value}** не найден!"),
                    ephemeral=True,
                )
                if source is not None:
                    await delete_select_message(source)
                return
            if not can_delete_owned(interaction.user, row["created_by"]):
                await interaction.response.send_message(
                    embed=_notice_embed(
                        "Удалять можно только свои объекты "
                        "или при правах модерации."
                    ),
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(DeleteUpkeepModal(value))
            if source is not None:
                await delete_select_message(source)
            return


class UpkeepMenuView(View):
    """Постоянное меню на сообщении «Панель Владений Новгорода»."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Добавить",
        style=discord.ButtonStyle.green,
        emoji="➕",
        row=0,
        custom_id="upkeep_panel:add",
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.send_modal(AddUpkeepModal())

    @discord.ui.button(
        label="Обновить",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        row=0,
        custom_id="upkeep_panel:refresh",
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        updated = apply_decay_to_all_upkeep()
        upkeep_logger.info(
            f"{get_user_info(interaction)} refreshed upkeep panel "
            f"({updated} objects updated)"
        )
        await interaction.response.edit_message(
            embed=build_all_upkeep_status_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Редактировать",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        row=0,
        custom_id="upkeep_panel:edit",
    )
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_upkeep_select(
            interaction,
            action="edit",
            title="✏️ Редактирование содержания",
            description="Выберите объект из списка:",
            empty_message="Нет объектов для редактирования!",
        )

    @discord.ui.button(
        label="Удалить",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        row=1,
        custom_id="upkeep_panel:delete",
    )
    async def delete_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_upkeep_select(
            interaction,
            action="delete",
            title="🗑️ Удаление содержания",
            description="Выберите объект (свой или модерация):",
            empty_message=(
                "Нет объектов, которые вы можете удалить "
                "(свои или при правах модерации)!"
            ),
            color=discord.Color.red(),
        )

    @discord.ui.button(
        label="Очистить всё",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        row=1,
        custom_id="upkeep_panel:clear",
    )
    async def clear_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await prompt_clear_all_upkeep(interaction)
