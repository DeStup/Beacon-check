"""Модальные окна для маяков."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import discord
from discord.ui import Modal, TextInput

import config
from services import database as db
from services.beacon_service import refresh_beacon_panel
from utils.formatting import (
    format_priority,
    get_user_info,
    rate_from_priority,
    type_from_rate,
)
from utils.logging_setup import action_logger, error_logger
from utils.permissions import can_delete_owned


async def _update_location_title(
    interaction: discord.Interaction,
    message_link: Optional[str],
    new_title: str,
) -> None:
    if not message_link:
        return
    try:
        parts = message_link.rstrip("/").split("/")
        channel_id = int(parts[-2])
        message_id = int(parts[-1])
        channel = interaction.client.get_channel(channel_id)
        if channel is None:
            channel = await interaction.client.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)  # type: ignore[union-attr]
        if not message.embeds:
            return
        embed = message.embeds[0].copy()
        embed.title = new_title
        await message.edit(embed=embed)
    except (IndexError, ValueError, discord.HTTPException):
        pass


class EditBeaconModal(Modal, title="✏️ Редактирование маяка"):
    """Имя, тип (1/2), топливо и прочность."""

    def __init__(
        self,
        beacon_id: str,
        *,
        current_fuel: float,
        current_lifetime: float,
        current_rate: float,
    ) -> None:
        super().__init__()
        self.original_id = beacon_id
        beacon_type = type_from_rate(current_rate)
        self.beacon_id_input = TextInput(
            label="ID / имя маяка",
            placeholder="Например: BCN-001",
            required=True,
            max_length=20,
            default=beacon_id,
        )
        self.type_input = TextInput(
            label="Тип: 1 = Фронтовой, 2 = Тыловой",
            placeholder="1 или 2",
            required=True,
            max_length=1,
            default=str(beacon_type),
        )
        self.fuel_input = TextInput(
            label=f"Топливо (0-{int(config.MAX_FUEL)})",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=3,
            default=str(int(current_fuel)),
        )
        self.lifetime_input = TextInput(
            label=f"Прочность (0-{int(config.MAX_LIFETIME)}%)",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=3,
            default=str(int(current_lifetime)),
        )
        self.add_item(self.beacon_id_input)
        self.add_item(self.type_input)
        self.add_item(self.fuel_input)
        self.add_item(self.lifetime_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        original_id = self.original_id
        current = db.get_beacon(original_id)
        if not current:
            await interaction.response.send_message(
                f"❌ Маяк {original_id} не найден!",
                ephemeral=True,
            )
            return

        new_id = self.beacon_id_input.value.strip()
        if not new_id or len(new_id) > 20:
            await interaction.response.send_message(
                "❌ ID маяка должен быть от 1 до 20 символов!",
                ephemeral=True,
            )
            return

        try:
            beacon_type = int(self.type_input.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Тип должен быть числом: 1 или 2!",
                ephemeral=True,
            )
            return
        if beacon_type not in (
            config.BEACON_TYPE_FRONT,
            config.BEACON_TYPE_REAR,
        ):
            await interaction.response.send_message(
                "❌ Тип: **1** — Фронтовой, **2** — Тыловой!",
                ephemeral=True,
            )
            return

        old_fuel = float(current["current_fuel"])
        old_lifetime = float(current["current_lifetime"])
        old_rate = float(current["fuel_consumption_rate"])
        message_link = current["message_link"]
        new_rate = rate_from_priority(beacon_type)

        updates: dict[str, float] = {}
        changes: list[str] = []
        reset_status = False
        earned_refuel = False
        earned_repair = False
        fuel_added = 0.0
        lifetime_added = 0.0

        if new_id != original_id:
            if db.beacon_exists(new_id):
                await interaction.response.send_message(
                    f"❌ Маяк {new_id} уже существует!",
                    ephemeral=True,
                )
                return
            changes.append(f"имя: {original_id} → {new_id}")

        if new_rate != old_rate:
            updates["fuel_consumption_rate"] = new_rate
            changes.append(
                f"тип: {format_priority(old_rate)} → {format_priority(new_rate)}"
            )

        fuel_raw = self.fuel_input.value.strip()
        if fuel_raw:
            try:
                new_fuel = float(fuel_raw)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Топливо должно быть числом",
                    ephemeral=True,
                )
                return
            if new_fuel < 0 or new_fuel > config.MAX_FUEL:
                await interaction.response.send_message(
                    f"❌ Топливо: от 0 до {config.MAX_FUEL}",
                    ephemeral=True,
                )
                return
            if new_fuel != old_fuel:
                if new_fuel > old_fuel:
                    fuel_added = new_fuel - old_fuel
                    if fuel_added >= (config.MAX_FUEL / 2):
                        earned_refuel = True
                updates["current_fuel"] = new_fuel
                changes.append(f"топливо: {old_fuel:.1f} → {new_fuel:.1f}")
                reset_status = reset_status or (
                    (new_fuel / config.MAX_FUEL) * 100
                    >= config.WARNING_THRESHOLD
                )

        lifetime_raw = self.lifetime_input.value.strip()
        if lifetime_raw:
            try:
                new_lifetime = float(lifetime_raw)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Прочность должна быть числом",
                    ephemeral=True,
                )
                return
            if new_lifetime < 0 or new_lifetime > config.MAX_LIFETIME:
                await interaction.response.send_message(
                    f"❌ Прочность: от 0 до {config.MAX_LIFETIME}%",
                    ephemeral=True,
                )
                return
            if new_lifetime != old_lifetime:
                if new_lifetime > old_lifetime:
                    lifetime_added = new_lifetime - old_lifetime
                    if lifetime_added >= (config.MAX_LIFETIME / 2):
                        earned_repair = True
                updates["current_lifetime"] = new_lifetime
                changes.append(
                    f"прочность: {old_lifetime:.1f}% → {new_lifetime:.1f}%"
                )
                reset_status = reset_status or (
                    new_lifetime >= config.WARNING_THRESHOLD
                )

        if not changes:
            await interaction.response.send_message(
                "❌ Нет изменений!",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        username = interaction.user.name
        beacon_id = original_id

        try:
            if new_id != original_id:
                if not db.rename_beacon(original_id, new_id):
                    await interaction.response.send_message(
                        f"❌ Не удалось переименовать в {new_id}!",
                        ephemeral=True,
                    )
                    return
                beacon_id = new_id
                await _update_location_title(
                    interaction, message_link, new_id
                )

            if updates or reset_status:
                updated = db.update_beacon_fields(
                    beacon_id,
                    updates=updates,
                    low_status_sent=(
                        False if reset_status else None
                    ),
                )
                if not updated and updates:
                    await interaction.response.send_message(
                        f"❌ Маяк {beacon_id} не найден!",
                        ephemeral=True,
                    )
                    return

            if earned_refuel:
                db.increment_user_stat(user_id, username, "refueled")
                action_logger.info(
                    f"User {username} earned refuel point via edit for beacon "
                    f"{beacon_id}: added {fuel_added:.1f} fuel"
                )
            if earned_repair:
                db.increment_user_stat(user_id, username, "repaired")
                action_logger.info(
                    f"User {username} earned repair point via edit for beacon "
                    f"{beacon_id}: added {lifetime_added:.1f}% lifetime"
                )

            embed = discord.Embed(
                title="✏️ Изменён маяк",
                description=f"**{beacon_id}**",
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="Изменения",
                value="\n".join(f"• {change}" for change in changes),
                inline=False,
            )
            if message_link:
                embed.add_field(
                    name="",
                    value=f"[Перейти]({message_link})",
                    inline=False,
                )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )
            await refresh_beacon_panel(interaction.client)  # type: ignore[arg-type]

            action_logger.info(
                f"{get_user_info(interaction)} modal edited beacon "
                f"{original_id}: {', '.join(changes)}"
            )
        except Exception as exc:
            await interaction.response.send_message(
                f"❌ Ошибка: {exc}",
                ephemeral=True,
            )
            error_logger.error(
                f"{get_user_info(interaction)} Ошибка при редактировании: {exc}",
                exc_info=True,
            )


class DeleteBeaconModal(Modal, title="🗑️ Удаление маяка"):
    """Модальное окно удаления с подтверждением имени."""

    def __init__(self, beacon_id: Optional[str] = None) -> None:
        super().__init__()
        self.beacon_id_display = TextInput(
            label="ID маяка для удаления",
            placeholder="Например: BCN-001",
            required=True,
            max_length=20,
            default=beacon_id or "",
            style=discord.TextStyle.short,
        )
        self.confirm_name = TextInput(
            label="Подтверждение (введите ТОЧНОЕ название маяка)",
            placeholder="Введите ID маяка для подтверждения удаления",
            required=True,
            max_length=20,
            style=discord.TextStyle.short,
        )
        self.add_item(self.beacon_id_display)
        self.add_item(self.confirm_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        beacon_id = self.beacon_id_display.value
        if self.confirm_name.value != beacon_id:
            await interaction.response.send_message(
                f"❌ Ошибка подтверждения: введенное имя "
                f"'{self.confirm_name.value}' не совпадает с ID маяка '{beacon_id}'",
                ephemeral=True,
            )
            return

        try:
            result = db.get_beacon(beacon_id)
            if not result:
                await interaction.response.send_message(
                    f"❌ Маяк {beacon_id} не найден!",
                    ephemeral=True,
                )
                return

            if not can_delete_owned(
                interaction.user,
                result["created_by"] if "created_by" in result.keys() else None,
                result["username"],
            ):
                await interaction.response.send_message(
                    "❌ Удалять можно только свои маяки "
                    "или при правах модерации.",
                    ephemeral=True,
                )
                return

            priority_text = format_priority(float(result["fuel_consumption_rate"]))
            db.delete_beacon(beacon_id)

            embed = discord.Embed(
                title="🗑️ Маяк удалён",
                description=f"**{beacon_id}**",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            embed.add_field(
                name="",
                value=f"Удалил: {interaction.user.mention}",
                inline=False,
            )

            action_logger.info(
                f"{get_user_info(interaction)} modal deleted beacon {beacon_id} | "
                f"Fuel: {result['current_fuel']}/{config.MAX_FUEL}, "
                f"Lifetime: {result['current_lifetime']}%, Priority: {priority_text}"
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )
            await refresh_beacon_panel(interaction.client)  # type: ignore[arg-type]

        except Exception as exc:
            await interaction.response.send_message(
                f"❌ Ошибка при удалении: {exc}",
                ephemeral=True,
            )
            error_logger.error(
                f"{get_user_info(interaction)} Ошибка при удалении маяка "
                f"{beacon_id}: {exc}",
                exc_info=True,
            )
