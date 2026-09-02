"""Выпадающий список маяков."""

from __future__ import annotations

from typing import Sequence

import discord
from discord.ui import Select, View

import config
from handlers.views.modals import DeleteBeaconModal, EditBeaconModal, RefuelModal
from handlers.views.status import show_all_beacons_status, show_beacon_status
from services.database import Row
from utils.formatting import priority_emoji


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
            if action_type == "status":
                options.append(
                    discord.SelectOption(
                        label="📊 Показать все маяки",
                        value="all",
                        description="Показать статус всех маяков",
                        emoji="📋",
                    )
                )
            for beacon in beacons[:24]:
                options.append(
                    discord.SelectOption(
                        label=beacon["beacon_id"],
                        value=beacon["beacon_id"],
                        description=(
                            f"🔋{beacon['current_fuel']:.0f}/{int(config.MAX_FUEL)} | "
                            f"🔄{beacon['current_lifetime']:.0f}%"
                        ),
                        emoji=priority_emoji(beacon["fuel_consumption_rate"]),
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

        if self.action_type == "status":
            if beacon_id == "all":
                await show_all_beacons_status(interaction)
            else:
                await show_beacon_status(interaction, beacon_id)
            return

        if self.action_type == "refuel":
            await interaction.response.send_modal(RefuelModal(beacon_id))
            return
        if self.action_type == "edit":
            await interaction.response.send_modal(EditBeaconModal(beacon_id))
            return
        if self.action_type == "delete":
            await interaction.response.send_modal(DeleteBeaconModal(beacon_id))
            return
