"""Форматирование строк и типов маяков."""

from __future__ import annotations

import discord

import config


async def delete_select_message(
    source_interaction: discord.Interaction,
) -> None:
    """Удаляет ephemeral со списком — ответ interaction, который его создал."""
    try:
        await source_interaction.delete_original_response()
    except discord.HTTPException:
        pass


def get_user_info(interaction: discord.Interaction) -> str:
    """Строка с информацией о пользователе для логов."""
    return f"User: {interaction.user.name} (ID: {interaction.user.id})"


def rate_from_priority(priority: int) -> float:
    """Преобразует тип маяка (1 / 2) в fuel_consumption_rate."""
    if priority == 3:  # legacy «тыловой»
        priority = config.BEACON_TYPE_REAR
    return config.PRIORITY_RATES.get(
        priority,
        config.PRIORITY_RATES[config.BEACON_TYPE_REAR],
    )


def type_from_rate(rate: float) -> int:
    """Тип маяка (1 / 2) по fuel_consumption_rate."""
    front_rate = config.PRIORITY_RATES[config.BEACON_TYPE_FRONT]
    if rate == front_rate:
        return config.BEACON_TYPE_FRONT
    return config.BEACON_TYPE_REAR


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
