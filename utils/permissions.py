"""Проверки прав доступа."""

from __future__ import annotations

import discord

import config


def can_clear_beacons(user: discord.abc.User) -> bool:
    """Может ли пользователь очистить все маяки."""
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
