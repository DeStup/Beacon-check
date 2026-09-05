"""Форматирование строк и типов маяков."""

from __future__ import annotations

from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    import discord


def get_user_info(interaction: discord.Interaction) -> str:
    """Строка с информацией о пользователе для логов."""
    return f"User: {interaction.user.name} (ID: {interaction.user.id})"


def rate_from_priority(priority: int) -> float:
    """Преобразует тип маяка (1 / 3) в fuel_consumption_rate."""
    return config.PRIORITY_RATES.get(
        priority,
        config.PRIORITY_RATES[config.BEACON_TYPE_REAR],
    )


def format_priority(rate: float, *, with_number: bool = False) -> str:
    """Название типа маяка по fuel_consumption_rate."""
    front_rate = config.PRIORITY_RATES[config.BEACON_TYPE_FRONT]
    if rate == front_rate:
        label = config.BEACON_TYPE_LABELS[config.BEACON_TYPE_FRONT]
        return f"{label}({config.BEACON_TYPE_FRONT})" if with_number else label
    label = config.BEACON_TYPE_LABELS[config.BEACON_TYPE_REAR]
    return f"{label}({config.BEACON_TYPE_REAR})" if with_number else label


def priority_emoji(rate: float) -> str | None:
    """Эмодзи типа больше не используются."""
    return None


def format_duration_hours(hours: float) -> str:
    """Человекочитаемая длительность из дробных часов (напр. 3д 11ч 10м)."""
    if hours <= 0:
        return "0м"
    total_minutes = int(hours * 60)
    days, rem = divmod(total_minutes, 24 * 60)
    hrs, mins = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hrs or days:
        parts.append(f"{hrs}ч")
    parts.append(f"{mins}м")
    return " ".join(parts)
