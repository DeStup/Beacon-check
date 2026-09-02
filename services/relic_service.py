"""Таймер появления реликвии."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

import config
from utils.logging_setup import action_logger, error_logger

if TYPE_CHECKING:
    from bot import BeaconBot


class RelicTimer:
    """Управление asyncio-таймером реликвии для одного канала."""

    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self.timer_start_time: Optional[datetime] = None
        self.timer_duration: Optional[int] = None

    async def start_timer(
        self,
        bot: BeaconBot,
        minutes: int = config.DEFAULT_RELIC_MINUTES,
    ) -> Optional[asyncio.Task[None]]:
        """Запускает таймер; предупреждение за RELIC_WARNING_MINUTES до конца."""
        channel = bot.get_channel(self.channel_id)
        if not channel:
            error_logger.error(
                f"Channel {self.channel_id} not found for relic timer!"
            )
            return None

        if self.channel_id in self.tasks:
            self.tasks[self.channel_id].cancel()
            del self.tasks[self.channel_id]

        self.timer_start_time = datetime.now()
        self.timer_duration = minutes

        task = asyncio.create_task(self._run_timer(bot, minutes))
        self.tasks[self.channel_id] = task

        action_logger.info(
            f"Relic timer started in channel {channel.name} "
            f"(ID: {self.channel_id}) for {minutes} minutes"
        )
        return task

    async def _run_timer(self, bot: BeaconBot, minutes: int) -> None:
        try:
            channel = bot.get_channel(self.channel_id)
            if not channel:
                error_logger.error(
                    f"Channel {self.channel_id} not found for relic timer!"
                )
                return

            wait_time = (minutes - config.RELIC_WARNING_MINUTES) * 60
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            channel = bot.get_channel(self.channel_id)
            if not channel:
                error_logger.error(
                    f"Channel {self.channel_id} not found for relic timer!"
                )
                return

            appear_time = datetime.now() + timedelta(
                minutes=config.RELIC_WARNING_MINUTES
            )
            unix_timestamp = int(appear_time.timestamp())

            embed = discord.Embed(
                title="⚔️ РЕЛИКВИЯ СКОРО ПОЯВИТСЯ!",
                description=(
                    "Через ~10 минут появится реликвия. "
                    "Вооружайтесь и будьте готовы к бою!"
                ),
                color=discord.Color.gold(),
                timestamp=datetime.now(),
            )
            embed.add_field(
                name="⏰ Время появления",
                value=f"<t:{unix_timestamp}:f> (<t:{unix_timestamp}:R>)",
                inline=False,
            )
            embed.add_field(
                name="📢 Приготовьтесь!",
                value="Соберите команду и подготовьте снаряжение!",
                inline=True,
            )
            embed.set_footer(text="Не пропустите появление реликвии!")
            await channel.send(embed=embed)

            await asyncio.sleep(config.RELIC_WARNING_MINUTES * 60)

            self.tasks.pop(self.channel_id, None)
            self.timer_start_time = None
            self.timer_duration = None
            action_logger.info(
                f"Relic timer completed in channel {channel.name} "
                f"(ID: {self.channel_id})"
            )

        except asyncio.CancelledError:
            self.tasks.pop(self.channel_id, None)
            self.timer_start_time = None
            self.timer_duration = None
            action_logger.info(
                f"Relic timer cancelled in channel ID: {self.channel_id}"
            )
            raise

    def cancel_timer(self) -> bool:
        """Отменяет активный таймер."""
        task = self.tasks.pop(self.channel_id, None)
        if task is None:
            return False
        task.cancel()
        self.timer_start_time = None
        self.timer_duration = None
        return True

    def is_active(self) -> bool:
        return self.channel_id in self.tasks

    def get_remaining_time(self) -> Optional[float]:
        if (
            not self.is_active()
            or self.timer_start_time is None
            or self.timer_duration is None
        ):
            return None
        elapsed = (datetime.now() - self.timer_start_time).total_seconds()
        return max(0.0, self.timer_duration * 60 - elapsed)

    def get_remaining_time_formatted(self) -> str:
        remaining = self.get_remaining_time()
        if remaining is None:
            return "Неактивен"
        if remaining <= 0:
            return "0 минут"

        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)

        if hours > 0:
            return f"{hours} ч {minutes} мин {seconds} сек"
        if minutes > 0:
            return f"{minutes} мин {seconds} сек"
        return f"{seconds} сек"
