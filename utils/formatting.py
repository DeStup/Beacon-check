"""Форматирование строк и приоритетов маяков."""

from __future__ import annotations

from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    import discord


def get_user_info(interaction: discord.Interaction) -> str:
    """Строка с информацией о пользователе для логов."""
    return f"User: {interaction.user.name} (ID: {interaction.user.id})"


def rate_from_priority(priority: int) -> float:
    """Преобразует приоритет 1–3 в fuel_consumption_rate."""
    return config.PRIORITY_RATES.get(priority, config.PRIORITY_RATES[3])


def format_priority(rate: float, *, with_number: bool = False) -> str:
    """Текст приоритета с эмодзи по значению rate."""
    if rate == 1:
        return "🔴 Высокий(1)" if with_number else "🔴 Высокий"
    if rate == 1.5:
        return "🟡 Средний(2)" if with_number else "🟡 Средний"
    return "🟢 Низкий(3)" if with_number else "🟢 Низкий"


def priority_emoji(rate: float) -> str:
    """Эмодзи приоритета без текста."""
    if rate == 1:
        return "🔴"
    if rate == 1.5:
        return "🟡"
    return "🟢"


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
