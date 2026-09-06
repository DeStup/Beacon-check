"""Модальные окна рабочих животных."""

from __future__ import annotations

from datetime import datetime

import discord
from discord.ui import Modal, TextInput

import config
from services import database as db
from services.feed_service import (
    animal_display,
    animal_label,
    refresh_feed_panel,
    snapshot_feed,
)
from utils.formatting import get_user_info
from utils.logging_setup import error_logger, feed_logger
from utils.permissions import can_delete_owned


def _error_embed(description: str) -> discord.Embed:
    return discord.Embed(
        title="❌ Ошибка",
        description=description,
        color=discord.Color.red(),
    )


class AddFeedModal(Modal):
    def __init__(self, animal_type: str) -> None:
        kind = animal_label(animal_type)
        super().__init__(title=f"➕ Добавить: {kind}")
        self.animal_type = animal_type
        self.name_input = TextInput(
            label="Местоположение",
            placeholder="Кузня №1",
            required=True,
            max_length=config.MAX_FEED_NAME_LENGTH,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                embed=_error_embed("Местоположение не может быть пустым!"),
                ephemeral=True,
            )
            return
        if db.feed_exists(name):
            await interaction.response.send_message(
                embed=_error_embed(
                    f"Животное в **{name}** уже есть!"
                ),
                ephemeral=True,
            )
            return

        animal_type = self.animal_type
        try:
            db.insert_feed(
                name=name,
                animal_type=animal_type,
                satiety=config.FEED_MAX_SATIETY,
                created_by=str(interaction.user.id),
            )
            feed_logger.info(
                f"{get_user_info(interaction)} added feed "
                f"{animal_type}:{name}"
            )
            embed = discord.Embed(
                title="➕ Животное добавлено",
                description=animal_display(animal_type, name),
                color=discord.Color.green(),
            )
            await interaction.response.send_message(
                embed=embed, ephemeral=True
            )
            await refresh_feed_panel(interaction.client)  # type: ignore[arg-type]
        except Exception as exc:
            error_logger.error(
                f"{get_user_info(interaction)} feed add failed: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )


class EditFeedModal(Modal, title="✏️ Редактировать животное"):
    def __init__(self, object_name: str) -> None:
        super().__init__()
        row = db.get_feed_by_name(object_name)
        snap = snapshot_feed(row) if row else None
        self.object_id = int(row["id"]) if row else 0
        self.animal_type = snap["animal_type"] if snap else "horse"
        self.original_name = object_name

        self.name_input = TextInput(
            label="Местоположение",
            required=True,
            max_length=config.MAX_FEED_NAME_LENGTH,
            default=object_name,
            placeholder="Кузня №1",
        )
        self.satiety_input = TextInput(
            label="Сытость % (0–100)",
            required=True,
            max_length=6,
            default=(
                str(int(snap["satiety"]))
                if snap
                else str(int(config.FEED_MAX_SATIETY))
            ),
        )
        self.add_item(self.name_input)
        self.add_item(self.satiety_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.object_id:
            await interaction.response.send_message(
                embed=_error_embed("Животное не найдено."),
                ephemeral=True,
            )
            return
        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                embed=_error_embed("Местоположение не может быть пустым!"),
                ephemeral=True,
            )
            return
        other = db.get_feed_by_name(name)
        if other is not None and int(other["id"]) != self.object_id:
            await interaction.response.send_message(
                embed=_error_embed(
                    f"Животное в **{name}** уже есть!"
                ),
                ephemeral=True,
            )
            return
        try:
            satiety = float(self.satiety_input.value.replace(",", "."))
        except ValueError as exc:
            await interaction.response.send_message(
                embed=_error_embed(f"Некорректные данные: {exc}"),
                ephemeral=True,
            )
            return
        if satiety < 0 or satiety > config.FEED_MAX_SATIETY:
            await interaction.response.send_message(
                embed=_error_embed("Сытость должна быть от 0 до 100."),
                ephemeral=True,
            )
            return

        animal_type = self.animal_type
        try:
            db.update_feed(
                self.object_id,
                name=name,
                satiety=satiety,
                last_updated=datetime.now().isoformat(),
                low_warning_sent=satiety < config.FEED_WARNING_THRESHOLD,
                death_notified=satiety <= 0,
            )
            feed_logger.info(
                f"{get_user_info(interaction)} edited feed "
                f"{self.original_name}→{name} satiety={satiety}"
            )
            embed = discord.Embed(
                title="✏️ Животное обновлено",
                description=animal_display(animal_type, name),
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(
                embed=embed, ephemeral=True
            )
            await refresh_feed_panel(interaction.client)  # type: ignore[arg-type]
        except Exception as exc:
            error_logger.error(
                f"{get_user_info(interaction)} feed edit failed: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )


class DeleteFeedModal(Modal, title="🗑️ Удалить животное"):
    def __init__(self, object_name: str) -> None:
        super().__init__()
        self.name_display = TextInput(
            label="Имя",
            required=True,
            max_length=config.MAX_FEED_NAME_LENGTH,
            default=object_name,
            placeholder="Кузня №1",
        )
        self.confirm_name = TextInput(
            label="Подтверждение (введите ТОЧНОЕ имя)",
            placeholder=object_name,
            required=True,
            max_length=config.MAX_FEED_NAME_LENGTH,
        )
        self.add_item(self.name_display)
        self.add_item(self.confirm_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.name_display.value.strip()
        confirm = self.confirm_name.value.strip()
        if name != confirm:
            await interaction.response.send_message(
                embed=_error_embed(
                    f"Подтверждение не совпадает с именем «{name}»"
                ),
                ephemeral=True,
            )
            return
        row = db.get_feed_by_name(name)
        if not row:
            await interaction.response.send_message(
                embed=_error_embed(f"Животное **{name}** не найдено!"),
                ephemeral=True,
            )
            return
        if not can_delete_owned(interaction.user, row["created_by"]):
            await interaction.response.send_message(
                embed=_error_embed(
                    "Удалять можно только своих животных "
                    "или при правах модерации."
                ),
                ephemeral=True,
            )
            return
        snap = snapshot_feed(row)
        db.delete_feed(name)
        feed_logger.info(
            f"{get_user_info(interaction)} deleted feed {name} "
            f"type={snap['animal_type']}"
        )
        embed = discord.Embed(
            title="🗑️ Животное удалено",
            description=animal_display(snap["animal_type"], name),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await refresh_feed_panel(interaction.client)  # type: ignore[arg-type]
