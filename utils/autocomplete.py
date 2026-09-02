"""Автодополнение для slash-команд."""

from __future__ import annotations

from typing import List

import discord
from discord import app_commands

from services import database as db
from utils.formatting import priority_emoji


async def get_minute_options(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[int]]:
    """Варианты минут для /relic."""
    options = [
        (90, "90 минут (1 час 30 минут)"),
        (60, "60 минут (1 час)"),
        (120, "120 минут (2 часа)"),
        (30, "30 минут"),
        (45, "45 минут"),
        (15, "15 минут"),
    ]
    choices: List[app_commands.Choice[int]] = []
    for value, name in options:
        if not current or (current.isdigit() and str(value).startswith(current)):
            choices.append(app_commands.Choice(name=name, value=value))
    return choices[:25]


async def get_beacon_ids(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Список ID маяков для автодополнения."""
    beacons = db.list_beacon_ids()
    choices: List[app_commands.Choice[str]] = []
    for beacon_id in beacons:
        if not current or current.lower() in beacon_id.lower():
            choices.append(app_commands.Choice(name=beacon_id, value=beacon_id))
    return choices[:25]


async def get_beacon_ids_with_details(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """ID маяков с кратким статусом для автодополнения."""
    beacons = db.list_beacons_summary()
    choices: List[app_commands.Choice[str]] = []
    for beacon in beacons:
        beacon_id = beacon["beacon_id"]
        emoji = priority_emoji(beacon["fuel_consumption_rate"])
        display_name = (
            f"{emoji} {beacon_id} "
            f"(🔋{beacon['current_fuel']:.0f} | 🔄{beacon['current_lifetime']:.0f}%)"
        )
        if (
            not current
            or current.lower() in beacon_id.lower()
            or current.lower() in display_name.lower()
        ):
            choices.append(
                app_commands.Choice(name=display_name[:100], value=beacon_id)
            )
    return choices[:25]
