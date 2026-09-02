"""Автодополнение для slash-команд."""

from __future__ import annotations

from typing import List, Sequence, Tuple

import discord
from discord import app_commands

# Варианты длительности для autocomplete /relic start
RELIC_MINUTE_OPTIONS: Sequence[Tuple[int, str]] = (
    (90, "90 минут (1 час 30 минут)"),
    (60, "60 минут (1 час)"),
    (120, "120 минут (2 часа)"),
    (30, "30 минут"),
    (45, "45 минут"),
    (15, "15 минут"),
)


async def get_minute_options(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[int]]:
    """Варианты минут для /relic start."""
    choices: List[app_commands.Choice[int]] = []
    for value, name in RELIC_MINUTE_OPTIONS:
        if not current or (current.isdigit() and str(value).startswith(current)):
            choices.append(app_commands.Choice(name=name, value=value))
    return choices[:25]
