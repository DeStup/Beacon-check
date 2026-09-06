"""Модальные окна для содержания (upkeep)."""

from __future__ import annotations

from datetime import datetime

import discord
from discord.ui import Modal, TextInput

import config
from services import database as db
from services.upkeep_service import (
    display_silver_amount,
    display_silver_rate,
    refresh_upkeep_panel,
    snapshot_upkeep,
)
from utils.formatting import get_user_info
from utils.logging_setup import error_logger, upkeep_logger
from utils.permissions import can_delete_owned


def _parse_positive_float(raw: str, *, field: str) -> float:
    value = float(raw.replace(",", ".").strip())
    if value < 0:
        raise ValueError(f"{field} не может быть отрицательным")
    return value


def _error_embed(description: str) -> discord.Embed:
    return discord.Embed(
        title="❌ Ошибка",
        description=description,
        color=discord.Color.red(),
    )


class AddUpkeepModal(Modal, title="➕ Добавить объект содержания"):
    def __init__(self) -> None:
        super().__init__()
        self.name_input = TextInput(
            label="Название объекта",
            placeholder="Например: Keep North",
            required=True,
            max_length=config.MAX_UPKEEP_NAME_LENGTH,
        )
        self.rate_input = TextInput(
            label="Серебро в час (содержание)",
            placeholder="Например: 120",
            required=True,
            max_length=20,
        )
        self.amount_input = TextInput(
            label="Серебро на складе",
            placeholder="Например: 5000",
            required=True,
            max_length=20,
        )
        self.add_item(self.name_input)
        self.add_item(self.rate_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                embed=_error_embed("Название не может быть пустым!"),
                ephemeral=True,
            )
            return
        if db.upkeep_exists(name):
            await interaction.response.send_message(
                embed=_error_embed(
                    f"Объект с именем **{name}** уже существует!"
                ),
                ephemeral=True,
            )
            return
        try:
            rate = _parse_positive_float(
                self.rate_input.value, field="Содержание"
            )
            amount = _parse_positive_float(
                self.amount_input.value, field="Склад"
            )
        except ValueError as exc:
            await interaction.response.send_message(
                embed=_error_embed(f"Некорректное число: {exc}"),
                ephemeral=True,
            )
            return

        try:
            db.insert_upkeep(
                name=name,
                silver_per_hour=rate,
                silver_amount=amount,
                created_by=str(interaction.user.id),
            )
            upkeep_logger.info(
                f"{get_user_info(interaction)} added upkeep {name} | "
                f"rate={rate}, amount={amount}"
            )
            embed = discord.Embed(
                title="➕ Объект содержания добавлен",
                description=f"**{name}**",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await refresh_upkeep_panel(interaction.client)  # type: ignore[arg-type]
        except Exception as exc:
            error_logger.error(
                f"{get_user_info(interaction)} upkeep add failed: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )


class EditUpkeepModal(Modal, title="✏️ Редактировать содержание"):
    def __init__(self, object_name: str) -> None:
        super().__init__()
        row = db.get_upkeep_by_name(object_name)
        snap = snapshot_upkeep(row) if row else None
        self.object_id = int(row["id"]) if row else 0
        self.original_name = object_name

        self.name_input = TextInput(
            label="Название объекта",
            required=True,
            max_length=config.MAX_UPKEEP_NAME_LENGTH,
            default=object_name,
        )
        self.rate_input = TextInput(
            label="Серебро в час (содержание)",
            required=True,
            max_length=20,
            default=(
                str(display_silver_rate(snap["silver_per_hour"]))
                if snap
                else ""
            ),
        )
        self.amount_input = TextInput(
            label="Серебро на складе",
            required=True,
            max_length=20,
            default=(
                str(display_silver_amount(snap["silver_amount"]))
                if snap
                else ""
            ),
        )
        self.add_item(self.name_input)
        self.add_item(self.rate_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.object_id:
            await interaction.response.send_message(
                embed=_error_embed("Объект не найден!"),
                ephemeral=True,
            )
            return

        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message(
                embed=_error_embed("Название не может быть пустым!"),
                ephemeral=True,
            )
            return

        if name != self.original_name and db.upkeep_exists(name):
            await interaction.response.send_message(
                embed=_error_embed(
                    f"Объект с именем **{name}** уже существует!"
                ),
                ephemeral=True,
            )
            return

        try:
            rate = _parse_positive_float(
                self.rate_input.value, field="Содержание"
            )
            amount = _parse_positive_float(
                self.amount_input.value, field="Склад"
            )
        except ValueError as exc:
            await interaction.response.send_message(
                embed=_error_embed(f"Некорректное число: {exc}"),
                ephemeral=True,
            )
            return

        try:
            db.update_upkeep(
                self.object_id,
                name=name,
                silver_per_hour=rate,
                silver_amount=amount,
                last_updated=datetime.now().isoformat(),
                low_warning_sent=False,
            )
            upkeep_logger.info(
                f"{get_user_info(interaction)} edited upkeep "
                f"{self.original_name}→{name} | rate={rate}, amount={amount}"
            )
            embed = discord.Embed(
                title="✏️ Объект содержания обновлён",
                description=f"**{name}**",
                color=discord.Color.blue(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await refresh_upkeep_panel(interaction.client)  # type: ignore[arg-type]
        except Exception as exc:
            error_logger.error(
                f"{get_user_info(interaction)} upkeep edit failed: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )


class DeleteUpkeepModal(Modal, title="🗑️ Удалить содержание"):
    def __init__(self, object_name: str) -> None:
        super().__init__()
        self.name_display = TextInput(
            label="Название объекта",
            required=True,
            max_length=config.MAX_UPKEEP_NAME_LENGTH,
            default=object_name,
        )
        self.confirm_name = TextInput(
            label="Подтверждение (введите ТОЧНОЕ название)",
            placeholder="Введите название для подтверждения",
            required=True,
            max_length=config.MAX_UPKEEP_NAME_LENGTH,
        )
        self.add_item(self.name_display)
        self.add_item(self.confirm_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.name_display.value.strip()
        if self.confirm_name.value.strip() != name:
            await interaction.response.send_message(
                embed=_error_embed(
                    f"Подтверждение не совпадает с названием «{name}»"
                ),
                ephemeral=True,
            )
            return

        row = db.get_upkeep_by_name(name)
        if not row:
            await interaction.response.send_message(
                embed=_error_embed(f"Объект **{name}** не найден!"),
                ephemeral=True,
            )
            return

        if not can_delete_owned(interaction.user, row["created_by"]):
            await interaction.response.send_message(
                embed=_error_embed(
                    "Удалять можно только свои объекты "
                    "или при правах модерации."
                ),
                ephemeral=True,
            )
            return

        snap = snapshot_upkeep(row)
        db.delete_upkeep(name)
        upkeep_logger.info(
            f"{get_user_info(interaction)} deleted upkeep {name} | "
            f"rate={snap['silver_per_hour']}, amount={snap['silver_amount']:.1f}"
        )
        embed = discord.Embed(
            title="🗑️ Объект содержания удалён",
            description=f"**{name}**",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await refresh_upkeep_panel(interaction.client)  # type: ignore[arg-type]
