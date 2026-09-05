"""Выпадающий список маяков и редактирование типа."""

from __future__ import annotations

from typing import Sequence

import discord
from discord.ui import Button, Select, View

import config
from handlers.views.modals import DeleteBeaconModal, EditBeaconModal
from services import database as db
from services.beacon_service import refresh_beacon_panel
from services.database import Row
from utils.formatting import format_priority, get_user_info, rate_from_priority
from utils.logging_setup import action_logger, error_logger


class BeaconSelectView(View):
    """View с выпадающим списком маяков."""

    def __init__(
        self,
        action_type: str,
        user_id: int,
        beacons: Sequence[Row],
    ) -> None:
        super().__init__(timeout=60)
        self.action_type = action_type
        self.user_id = user_id
        self.add_item(BeaconSelect(action_type, beacons))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Вы не можете использовать это меню!",
                ephemeral=True,
            )
            return False
        return True


class BeaconSelect(Select):
    """Select-меню по маякам."""

    def __init__(self, action_type: str, beacons: Sequence[Row]) -> None:
        self.action_type = action_type

        if not beacons:
            options = [
                discord.SelectOption(
                    label="Нет активных маяков",
                    value="none",
                    description="Сначала добавьте маяк",
                    emoji="⚠️",
                )
            ]
        else:
            options: list[discord.SelectOption] = []
            for beacon in beacons[:25]:
                options.append(
                    discord.SelectOption(
                        label=beacon["beacon_id"],
                        value=beacon["beacon_id"],
                        description=(
                            f"🔋{beacon['current_fuel']:.0f}/{int(config.MAX_FUEL)} | "
                            f"🔄{beacon['current_lifetime']:.0f}%"
                        ),
                    )
                )

        super().__init__(
            placeholder="🔍 Выберите маяк из списка...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "none":
            await interaction.response.send_message(
                "❌ Нет активных маяков. Сначала добавьте маяк через `/beacon add`",
                ephemeral=True,
            )
            return

        beacon_id = self.values[0]

        if self.action_type == "edit":
            row = db.get_beacon(beacon_id)
            if not row:
                await interaction.response.send_message(
                    f"❌ Маяк {beacon_id} не найден!",
                    ephemeral=True,
                )
                return
            embed = discord.Embed(
                title=f"✏️ Редактирование: {beacon_id}",
                description=(
                    "Выберите **тип** в списке ниже.\n"
                    "Топливо и прочность — кнопкой."
                ),
                color=discord.Color.gold(),
            )
            await interaction.response.send_message(
                embed=embed,
                view=EditBeaconView(
                    beacon_id,
                    interaction.user.id,
                    float(row["fuel_consumption_rate"]),
                ),
                ephemeral=True,
            )
            return
        if self.action_type == "delete":
            await interaction.response.send_modal(DeleteBeaconModal(beacon_id))
            return


class BeaconTypeSelect(Select):
    """Фиксированный выбор типа: Фронтовой / Тыловой."""

    def __init__(self, beacon_id: str, current_rate: float) -> None:
        self.beacon_id = beacon_id
        front_rate = config.PRIORITY_RATES[config.BEACON_TYPE_FRONT]
        is_front = current_rate == front_rate
        options = [
            discord.SelectOption(
                label=config.BEACON_TYPE_LABELS[config.BEACON_TYPE_FRONT],
                value=str(config.BEACON_TYPE_FRONT),
                description="Быстрый расход топлива",
                default=is_front,
            ),
            discord.SelectOption(
                label=config.BEACON_TYPE_LABELS[config.BEACON_TYPE_REAR],
                value=str(config.BEACON_TYPE_REAR),
                description="Обычный",
                default=not is_front,
            ),
        ]
        super().__init__(
            placeholder="Тип маяка…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        beacon_id = self.beacon_id
        priority = int(self.values[0])
        rate = rate_from_priority(priority)
        current = db.get_beacon(beacon_id)
        if not current:
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} не найден!",
                ephemeral=True,
            )
            return

        old_rate = float(current["fuel_consumption_rate"])
        if old_rate == rate:
            await interaction.response.send_message(
                f"Тип уже **{format_priority(rate)}**.",
                ephemeral=True,
            )
            return

        try:
            db.update_beacon_fields(
                beacon_id,
                updates={"fuel_consumption_rate": rate},
            )
            await refresh_beacon_panel(interaction.client)  # type: ignore[arg-type]
            action_logger.info(
                f"{get_user_info(interaction)} set beacon {beacon_id} type "
                f"{format_priority(old_rate)} → {format_priority(rate)}"
            )
            embed = discord.Embed(
                title="✏️ Изменён маяк",
                description=f"**{beacon_id}**",
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="Изменения",
                value=(
                    f"• тип: {format_priority(old_rate)} → "
                    f"{format_priority(rate)}"
                ),
                inline=False,
            )
            if current["message_link"]:
                embed.add_field(
                    name="",
                    value=f"[Перейти]({current['message_link']})",
                    inline=False,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as exc:
            error_logger.error(
                f"{get_user_info(interaction)} type edit failed: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(
                f"❌ Ошибка: {exc}",
                ephemeral=True,
            )


class EditBeaconView(View):
    """Редактирование: Select типа + модалка топлива/прочности."""

    def __init__(
        self,
        beacon_id: str,
        user_id: int,
        current_rate: float,
    ) -> None:
        super().__init__(timeout=120)
        self.beacon_id = beacon_id
        self.user_id = user_id
        self.add_item(BeaconTypeSelect(beacon_id, current_rate))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Вы не можете использовать это меню!",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Топливо и прочность",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        row=1,
    )
    async def stats_button(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.send_modal(EditBeaconModal(self.beacon_id))
