"""Slash-команды мониторинга содержания (серебро).

Команды /upkeep сняты — панель Новгорода обновляется автоматически.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    pass
