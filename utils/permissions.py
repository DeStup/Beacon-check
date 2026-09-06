"""Проверки прав доступа."""

from __future__ import annotations

from typing import Optional

import discord

import config


def can_clear_beacons(user: discord.abc.User) -> bool:
    """Может ли пользователь очистить все маяки / upkeep."""
    if user.id in config.CLEAR_ALLOWED_USER_IDS:
        return True
    if isinstance(user, discord.Member):
        perms = user.guild_permissions
        return bool(
            perms.administrator
            or perms.manage_guild
            or perms.manage_channels
        )
    return False


def can_manage_upkeep(user: discord.abc.User) -> bool:
    """Модерация: удаление / очистка объектов upkeep."""
    return can_clear_beacons(user) or is_moderator(user)


def is_moderator(user: discord.abc.User) -> bool:
    """Админ / manage_guild / manage_messages."""
    if isinstance(user, discord.Member):
        perms = user.guild_permissions
        return bool(
            perms.administrator
            or perms.manage_guild
            or perms.manage_messages
        )
    return False


def _creator_markers(user: discord.abc.User) -> set[str]:
    markers = {str(user.id), user.name}
    global_name = getattr(user, "global_name", None)
    if global_name:
        markers.add(global_name)
    display_name = getattr(user, "display_name", None)
    if display_name:
        markers.add(display_name)
    return markers


def is_record_creator(
    user: discord.abc.User,
    *created_by_values: Optional[str],
) -> bool:
    """Автор записи: created_by / username совпадает с id или ником."""
    markers = _creator_markers(user)
    for value in created_by_values:
        if value and value in markers:
            return True
    return False


def can_delete_owned(
    user: discord.abc.User,
    *created_by_values: Optional[str],
) -> bool:
    """Удаление: автор объекта или права модерации."""
    if can_manage_upkeep(user):
        return True
    return is_record_creator(user, *created_by_values)
