"""Меню и select для панели кормёжки."""

from __future__ import annotations

from typing import Sequence

import discord
from discord.ui import Button, Select, View

import config
from handlers.views.feed_modals import (
    AddFeedModal,
    DeleteFeedModal,
    EditFeedModal,
)
from services import database as db
from services.database import Row
from services.feed_service import (
    animal_emoji,
    animal_label,
    apply_decay_to_all_feed,
    build_all_feed_status_embed,
    refresh_feed_panel,
    snapshot_feed,
)
from utils.formatting import delete_select_message, get_user_info
from utils.logging_setup import feed_logger
from utils.permissions import can_delete_owned, can_manage_upkeep


def _notice_embed(
    description: str,
    *,
    title: str = "❌ Ошибка",
    color: discord.Color = discord.Color.red(),
) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class AddAnimalTypeView(View):
    """Фиксированный выбор типа перед модалкой имени."""

    def __init__(self, source_interaction: discord.Interaction) -> None:
        super().__init__(timeout=120)
        self.source_interaction = source_interaction
        options = [
            discord.SelectOption(
                label=animal_label(key),
                value=key,
                emoji=animal_emoji(key),
                description=(
                    f"Сытость падает за "
                    f"{config.FEED_ANIMAL_HOURS_TO_EMPTY[key]:g} ч"
                ),
            )
            for key in config.FEED_ANIMAL_HOURS_TO_EMPTY
        ]
        self.add_item(AddAnimalTypeSelect(options))


class AddAnimalTypeSelect(Select):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Выберите тип животного…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        animal_type = self.values[0]
        await interaction.response.send_modal(AddFeedModal(animal_type))
        view = self.view
        if isinstance(view, AddAnimalTypeView):
            await delete_select_message(view.source_interaction)


async def open_feed_select(
    interaction: discord.Interaction,
    *,
    action: str,
    title: str,
    description: str,
    empty_message: str,
    color: discord.Color = discord.Color.blue(),
) -> None:
    rows = db.list_feed_summary()
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
    view = FeedSelectView(action, interaction.user.id, rows, interaction)
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=True
    )


class ClearFeedConfirmView(View):
    def __init__(self, requester_id: int) -> None:
        super().__init__(timeout=60)
        self.requester_id = requester_id

    async def interaction_check(
        self, interaction: discord.Interaction
    ) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Это подтверждение не для вас.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Да, очистить всё",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        count = db.clear_all_feed()
        feed_logger.info(
            f"{get_user_info(interaction)} cleared all feed ({count})"
        )
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🗑️ Список очищен",
                description=f"Удалено животных: **{count}**",
                color=discord.Color.red(),
            ),
            view=None,
        )
        await refresh_feed_panel(interaction.client)  # type: ignore[arg-type]

    @discord.ui.button(
        label="Отмена",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Отменено",
                description="Очистка не выполнена.",
                color=discord.Color.dark_grey(),
            ),
            view=None,
        )


async def prompt_clear_all_feed(interaction: discord.Interaction) -> None:
    if not can_manage_upkeep(interaction.user):
        await interaction.response.send_message(
            embed=_notice_embed("Недостаточно прав (нужна модерация)."),
            ephemeral=True,
        )
        return
    count = len(db.list_feed_summary())
    if count == 0:
        await interaction.response.send_message(
            embed=_notice_embed(
                "Нечего удалять.",
                title="📭 Пусто",
                color=discord.Color.orange(),
            ),
            ephemeral=True,
        )
        return
    embed = discord.Embed(
        title="⚠️ Очистить всех рабочих животных?",
        description=f"Будет удалено животных: **{count}**",
        color=discord.Color.red(),
    )
    await interaction.response.send_message(
        embed=embed,
        view=ClearFeedConfirmView(interaction.user.id),
        ephemeral=True,
    )


class FeedSelectView(View):
    def __init__(
        self,
        action_type: str,
        requester_id: int,
        rows: Sequence[Row],
        source_interaction: discord.Interaction,
    ) -> None:
        super().__init__(timeout=120)
        self.action_type = action_type
        self.requester_id = requester_id
        self.source_interaction = source_interaction
        options: list[discord.SelectOption] = []
        for row in rows[:25]:
            snap = snapshot_feed(row)
            pct = int(snap["satiety"])
            status = "мертв" if snap["is_dead"] else f"{pct}%"
            options.append(
                discord.SelectOption(
                    label=snap["name"][:100],
                    value=snap["name"],
                    description=(
                        f"{animal_label(snap['animal_type'])} · {status}"
                    )[:100],
                    emoji=animal_emoji(snap["animal_type"]),
                )
            )
        self.add_item(FeedSelect(options, action_type, requester_id))

    async def interaction_check(
        self, interaction: discord.Interaction
    ) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Этот список не для вас.",
                ephemeral=True,
            )
            return False
        return True


class FeedSelect(Select):
    def __init__(
        self,
        options: list[discord.SelectOption],
        action_type: str,
        requester_id: int,
    ) -> None:
        super().__init__(
            placeholder="Выберите животное…",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.action_type = action_type
        self.requester_id = requester_id

    def _source(self) -> discord.Interaction | None:
        view = self.view
        if isinstance(view, FeedSelectView):
            return view.source_interaction
        return None

    async def callback(self, interaction: discord.Interaction) -> None:
        source = self._source()
        value = self.values[0]
        if self.action_type == "edit":
            await interaction.response.send_modal(EditFeedModal(value))
            if source is not None:
                await delete_select_message(source)
            return
        if self.action_type == "delete":
            row = db.get_feed_by_name(value)
            if not row:
                await interaction.response.send_message(
                    embed=_notice_embed(f"Животное **{value}** не найдено!"),
                    ephemeral=True,
                )
                if source is not None:
                    await delete_select_message(source)
                return
            if not can_delete_owned(interaction.user, row["created_by"]):
                await interaction.response.send_message(
                    embed=_notice_embed(
                        "Удалять можно только своих животных "
                        "или при правах модерации."
                    ),
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(DeleteFeedModal(value))
            if source is not None:
                await delete_select_message(source)
            return


class FeedMenuView(View):
    """Постоянное меню «Панель Сытости Животных»."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Добавить",
        style=discord.ButtonStyle.green,
        emoji="➕",
        row=0,
        custom_id="feed_panel:add",
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        embed = discord.Embed(
            title="➕ Добавить животное",
            description="Выберите тип:",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=AddAnimalTypeView(interaction),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Обновить",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        row=0,
        custom_id="feed_panel:refresh",
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        updated = apply_decay_to_all_feed()
        feed_logger.info(
            f"{get_user_info(interaction)} refreshed feed panel "
            f"({updated} animals updated)"
        )
        await interaction.response.edit_message(
            embed=build_all_feed_status_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Редактировать",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        row=0,
        custom_id="feed_panel:edit",
    )
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_feed_select(
            interaction,
            action="edit",
            title="✏️ Редактирование",
            description="Выберите животное:",
            empty_message="Нет животных для редактирования!",
        )

    @discord.ui.button(
        label="Удалить",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        row=1,
        custom_id="feed_panel:delete",
    )
    async def delete_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await open_feed_select(
            interaction,
            action="delete",
            title="🗑️ Удаление",
            description="Выберите животное (своё или модерация):",
            empty_message=(
                "Нет животных, которые вы можете удалить "
                "(свои или при правах модерации)!"
            ),
            color=discord.Color.red(),
        )

    @discord.ui.button(
        label="Очистить всё",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        row=1,
        custom_id="feed_panel:clear",
    )
    async def clear_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await prompt_clear_all_feed(interaction)
