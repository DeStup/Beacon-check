"""Модальные окна для маяков."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import discord
from discord.ui import Modal, TextInput

import config
from services import database as db
from utils.formatting import format_priority, get_user_info, rate_from_priority
from utils.logging_setup import action_logger, error_logger


class RefuelModal(Modal, title="⛽ Заправка маяка"):
    """Модальное окно для заправки маяка."""

    def __init__(self, beacon_id: Optional[str] = None) -> None:
        super().__init__()
        self.beacon_id_input = TextInput(
            label="ID маяка",
            placeholder="Например: BCN-001",
            required=True,
            max_length=20,
            default=beacon_id or "",
        )
        self.amount_input = TextInput(
            label=f"Количество топлива (0-{int(config.MAX_FUEL)})",
            placeholder=f"Оставьте пустым для полной заправки ({int(config.MAX_FUEL)})",
            required=False,
            max_length=3,
        )
        self.add_item(self.beacon_id_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        amount = (
            float(self.amount_input.value)
            if self.amount_input.value
            else config.MAX_FUEL
        )
        beacon_id = self.beacon_id_input.value
        user_id = str(interaction.user.id)
        username = interaction.user.name

        try:
            result = db.refuel_beacon(beacon_id, amount)
            if result is None:
                await interaction.response.send_message(
                    f"❌ Маяк {beacon_id} не найден!",
                    ephemeral=True,
                )
                return

            added = result["added"]
            if added >= (config.MAX_FUEL / 2):
                db.increment_user_stat(user_id, username, "refueled")
                action_logger.info(
                    f"User {username} earned refuel point for beacon {beacon_id}: "
                    f"added {added:.1f} fuel (≥15)"
                )

            action_logger.info(
                f"{get_user_info(interaction)} modal refueled beacon {beacon_id} | "
                f"Added: {amount:.1f}, Real added: {added:.1f}, "
                f"Old: {result['old_fuel']:.1f}, "
                f"New: {result['new_fuel']:.1f}/{config.MAX_FUEL}"
            )

            embed = discord.Embed(
                title="⛽ Заправлен маяк",
                description=f"**{beacon_id}**",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Новое топливо",
                value=f"{result['new_fuel']:.1f}/{config.MAX_FUEL}",
            )
            embed.add_field(name="Добавлено", value=f"{added:.1f}")
            if result["message_link"]:
                embed.add_field(
                    name="",
                    value=f"🔗 [Перейти]({result['message_link']})",
                    inline=False,
                )
            embed.add_field(
                name="",
                value=f"Заправил: {interaction.user.mention}",
                inline=False,
            )

            await interaction.response.send_message(
                f"✅ Заправка маяка {beacon_id} выполнена!",
                ephemeral=True,
            )
            if interaction.channel:
                await interaction.channel.send(embed=embed)

        except Exception as exc:
            await interaction.response.send_message(
                f"❌ Ошибка: {exc}",
                ephemeral=True,
            )


class EditBeaconModal(Modal, title="✏️ Редактирование маяка"):
    """Модальное окно для редактирования маяка."""

    def __init__(self, beacon_id: Optional[str] = None) -> None:
        super().__init__()
        self.beacon_id_input = TextInput(
            label="ID маяка",
            placeholder="Например: BCN-001",
            required=True,
            max_length=20,
            default=beacon_id or "",
        )
        self.priority_input = TextInput(
            label="Новый приоритет (1-3)",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=1,
        )
        self.fuel_input = TextInput(
            label=f"Новое топливо (0-{int(config.MAX_FUEL)})",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=3,
        )
        self.lifetime_input = TextInput(
            label=f"Новая прочность (0-{int(config.MAX_LIFETIME)}%)",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=3,
        )
        self.add_item(self.beacon_id_input)
        self.add_item(self.priority_input)
        self.add_item(self.fuel_input)
        self.add_item(self.lifetime_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        beacon_id = self.beacon_id_input.value
        current = db.get_beacon(beacon_id)
        if not current:
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} не найден!",
                ephemeral=True,
            )
            return

        old_fuel = float(current["current_fuel"])
        old_lifetime = float(current["current_lifetime"])
        old_rate = float(current["fuel_consumption_rate"])
        message_link = current["message_link"]

        updates: dict[str, float] = {}
        changes: list[str] = []
        new_values: dict[str, float | str] = {}
        reset_status = False
        earned_refuel = False
        earned_repair = False
        fuel_added = 0.0
        lifetime_added = 0.0

        if self.priority_input.value:
            try:
                priority = int(self.priority_input.value)
                if priority not in (1, 2, 3):
                    await interaction.response.send_message(
                        "❌ Ошибка: приоритет должен быть 1, 2 или 3",
                        ephemeral=True,
                    )
                    return
                rate = rate_from_priority(priority)
                updates["fuel_consumption_rate"] = rate
                new_priority = format_priority(rate)
                changes.append(
                    f"приоритет: {format_priority(old_rate)} → {new_priority}"
                )
                new_values["priority"] = new_priority
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: приоритет должен быть числом",
                    ephemeral=True,
                )
                return
        else:
            new_values["priority"] = format_priority(old_rate)

        if self.fuel_input.value:
            try:
                new_fuel = float(self.fuel_input.value)
                if new_fuel > config.MAX_FUEL:
                    await interaction.response.send_message(
                        f"❌ Ошибка: топливо не может превышать {config.MAX_FUEL}",
                        ephemeral=True,
                    )
                    return
                if new_fuel > old_fuel:
                    fuel_added = new_fuel - old_fuel
                    if fuel_added >= (config.MAX_FUEL / 2):
                        earned_refuel = True
                updates["current_fuel"] = new_fuel
                changes.append(f"топливо: {old_fuel:.1f} → {new_fuel:.1f}")
                new_values["fuel"] = new_fuel
                reset_status = reset_status or (
                    (new_fuel / config.MAX_FUEL) * 100 >= config.WARNING_THRESHOLD
                )
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: топливо должно быть числом",
                    ephemeral=True,
                )
                return
        else:
            new_values["fuel"] = old_fuel

        if self.lifetime_input.value:
            try:
                new_lifetime = float(self.lifetime_input.value)
                if new_lifetime > config.MAX_LIFETIME:
                    await interaction.response.send_message(
                        f"❌ Ошибка: прочность не может превышать {config.MAX_LIFETIME}%",
                        ephemeral=True,
                    )
                    return
                if new_lifetime > old_lifetime:
                    lifetime_added = new_lifetime - old_lifetime
                    if lifetime_added >= (config.MAX_LIFETIME / 2):
                        earned_repair = True
                updates["current_lifetime"] = new_lifetime
                changes.append(
                    f"прочность: {old_lifetime:.1f}% → {new_lifetime:.1f}%"
                )
                new_values["lifetime"] = new_lifetime
                reset_status = reset_status or (
                    new_lifetime >= config.WARNING_THRESHOLD
                )
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: прочность должна быть числом",
                    ephemeral=True,
                )
                return
        else:
            new_values["lifetime"] = old_lifetime

        if not updates:
            await interaction.response.send_message(
                "❌ Не указаны данные для обновления!",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        username = interaction.user.name

        try:
            updated = db.update_beacon_fields(
                beacon_id,
                updates=updates,
                low_status_sent=not reset_status,
            )
            if not updated:
                await interaction.response.send_message(
                    f"❌ Маяк {beacon_id} не найден!",
                    ephemeral=True,
                )
                return

            if earned_refuel:
                db.increment_user_stat(user_id, username, "refueled")
                action_logger.info(
                    f"User {username} earned refuel point via edit for beacon "
                    f"{beacon_id}: added {fuel_added:.1f} fuel (≥15)"
                )
            if earned_repair:
                db.increment_user_stat(user_id, username, "repaired")
                action_logger.info(
                    f"User {username} earned repair point via edit for beacon "
                    f"{beacon_id}: added {lifetime_added:.1f}% lifetime (≥50%)"
                )

            embed = discord.Embed(
                title="✏️ Изменён маяк",
                description=f"**{beacon_id}**",
                color=discord.Color.gold(),
                timestamp=datetime.now(),
            )
            embed.add_field(
                name="🔋 Топливо",
                value=f"{float(new_values['fuel']):.1f}/{config.MAX_FUEL}",
                inline=True,
            )
            embed.add_field(
                name="🔄 Прочность",
                value=f"{float(new_values['lifetime']):.1f}%",
                inline=True,
            )
            embed.add_field(
                name="📊 Приоритет",
                value=str(new_values["priority"]),
                inline=True,
            )
            if changes:
                embed.add_field(
                    name="📝 Изменения",
                    value="\n".join(f"• {change}" for change in changes),
                    inline=False,
                )
            if message_link:
                embed.add_field(
                    name="",
                    value=f"🔗 [Перейти]({message_link})",
                    inline=False,
                )
            embed.add_field(
                name="",
                value=f"Отредактировал: {interaction.user.mention}",
                inline=False,
            )

            await interaction.response.send_message(
                f"✅ Данные маяка {beacon_id} успешно обновлены!",
                ephemeral=True,
            )
            if interaction.channel:
                await interaction.channel.send(embed=embed)

            action_logger.info(
                f"{get_user_info(interaction)} modal edited beacon {beacon_id}: "
                f"{', '.join(changes)}"
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
                f"✅ Маяк {beacon_id} успешно удалён!",
                ephemeral=True,
            )
            if interaction.channel:
                await interaction.channel.send(embed=embed)

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
