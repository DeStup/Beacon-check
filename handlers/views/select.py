"""Выпадающий список маяков."""

from __future__ import annotations

from typing import Sequence

import discord
from discord.ui import Select, View

import config
from handlers.views.modals import DeleteBeaconModal, EditBeaconModal
from services import database as db
from services.database import Row
from utils.formatting import delete_select_message
from utils.permissions import can_delete_owned


class BeaconSelectView(View):
    """View с выпадающим списком маяков."""

    def __init__(
        self,
        action_type: str,
        user_id: int,
        beacons: Sequence[Row],
        source_interaction: discord.Interaction,
    ) -> None:
        super().__init__(timeout=60)
        self.action_type = action_type
        self.user_id = user_id
        self.source_interaction = source_interaction
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

    def _source(self) -> discord.Interaction | None:
        view = self.view
        if isinstance(view, BeaconSelectView):
            return view.source_interaction
        return None

    async def callback(self, interaction: discord.Interaction) -> None:
        source = self._source()

        if self.values[0] == "none":
            await interaction.response.send_message(
                "❌ Нет активных маяков. Сначала добавьте маяк через `/beacon add`",
                ephemeral=True,
            )
            if source is not None:
                await delete_select_message(source)
            return

        beacon_id = self.values[0]
        row = db.get_beacon(beacon_id)
        if not row:
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} не найден!",
                ephemeral=True,
            )
            if source is not None:
                await delete_select_message(source)
            return

        if self.action_type == "edit":
            await interaction.response.send_modal(
                EditBeaconModal(
                    beacon_id,
                    current_fuel=float(row["current_fuel"]),
                    current_lifetime=float(row["current_lifetime"]),
                    current_rate=float(row["fuel_consumption_rate"]),
                )
            )
            if source is not None:
                await delete_select_message(source)
            return

        if self.action_type == "delete":
            if not can_delete_owned(
                interaction.user,
                row["created_by"] if "created_by" in row.keys() else None,
                row["username"],
            ):
                await interaction.response.send_message(
                    "❌ Удалять можно только свои маяки "
                    "или при правах модерации.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(DeleteBeaconModal(beacon_id))
            if source is not None:
                await delete_select_message(source)
            return
