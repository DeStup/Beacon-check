"""Хелперы для Discord embed."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

import discord

import config


def progress_bar(value: float, max_value: float, bar_length: int = 10) -> str:
    """Полоска прогресса из █ и ░."""
    if max_value <= 0:
        return "░" * bar_length
    percent = max(0.0, min(100.0, (value / max_value) * 100))
    filled = int(percent / (100 / bar_length))
    filled = max(0, min(bar_length, filled))
    return "█" * filled + "░" * (bar_length - filled)


def status_emoji(
    percent: float,
    threshold_warning: float = config.WARNING_THRESHOLD,
    threshold_critical: float = config.CRITICAL_THRESHOLD,
) -> str:
    """Эмодзи статуса по проценту."""
    if percent <= threshold_critical:
        return "💀"
    if percent <= threshold_warning:
        return "⚠️"
    return "✅"


def create_embed(
    title: str,
    description: str,
    color: discord.Color,
    fields: Optional[Sequence[tuple[str, str, bool]]] = None,
    footer: Optional[str] = None,
    timestamp: bool = True,
    link: Optional[str] = None,
) -> discord.Embed:
    """Стандартизированный embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now() if timestamp else None,
    )

    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    if link:
        embed.add_field(name="", value=f"🔗 [Перейти]({link})", inline=False)

    if footer:
        embed.add_field(name="", value=footer, inline=False)

    return embed
