"""Таймер появления реликвии с сохранением в relic_events."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

import config
from services import database as db
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
        self._event_id: Optional[int] = None
        self._warning_sent: bool = False

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
            task = self.tasks.pop(self.channel_id)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        started_at = datetime.now()
        event_id = db.create_relic_event(
            channel_id=self.channel_id,
            started_at=started_at,
            duration_minutes=minutes,
        )

        self.timer_start_time = started_at
        self.timer_duration = minutes
        self._event_id = event_id
        self._warning_sent = False

        task = asyncio.create_task(self._run_timer(bot))
        self.tasks[self.channel_id] = task

        action_logger.info(
            f"Relic timer started in channel {channel.name} "
            f"(ID: {self.channel_id}) for {minutes} minutes "
            f"(event_id={event_id})"
        )
        return task

    async def restore(self, bot: BeaconBot) -> bool:
        """Восстанавливает активный таймер из БД после рестарта. True если подняли."""
        if not self.channel_id:
            return False

        row = db.get_active_relic_event(self.channel_id)
        if row is None:
            return False

        started_at = datetime.fromisoformat(row["started_at"])
        duration = int(row["duration_minutes"])
        appear_at = started_at + timedelta(minutes=duration)
        now = datetime.now()

        if now >= appear_at:
            db.finish_relic_event(int(row["id"]), "completed")
            action_logger.info(
                f"Relic event {row['id']} already expired on restore; marked completed"
            )
            return False

        self.timer_start_time = started_at
        self.timer_duration = duration
        self._event_id = int(row["id"])
        self._warning_sent = bool(row["warning_sent"])

        if self.channel_id in self.tasks:
            self.tasks[self.channel_id].cancel()

        task = asyncio.create_task(self._run_timer(bot))
        self.tasks[self.channel_id] = task

        remaining = (appear_at - now).total_seconds()
        action_logger.info(
            f"Relic timer restored from DB (event_id={self._event_id}), "
            f"remaining ~{int(remaining)}s, warning_sent={self._warning_sent}"
        )
        return True

    async def _run_timer(self, bot: BeaconBot) -> None:
        event_id = self._event_id
        try:
            if (
                self.timer_start_time is None
                or self.timer_duration is None
                or event_id is None
            ):
                return

            appear_at = self.timer_start_time + timedelta(
                minutes=self.timer_duration
            )
            warning_at = appear_at - timedelta(
                minutes=config.RELIC_WARNING_MINUTES
            )

            if not self._warning_sent:
                wait_until_warning = (warning_at - datetime.now()).total_seconds()
                if wait_until_warning > 0:
                    await asyncio.sleep(wait_until_warning)

                channel = bot.get_channel(self.channel_id)
                if not channel:
                    error_logger.error(
                        f"Channel {self.channel_id} not found for relic timer!"
                    )
                    db.finish_relic_event(event_id, "cancelled")
                    self.tasks.pop(self.channel_id, None)
                    self.timer_start_time = None
                    self.timer_duration = None
                    self._event_id = None
                    self._warning_sent = False
                    return

                unix_timestamp = int(appear_at.timestamp())
                embed = discord.Embed(
                    title="⚔️ РЕЛИКВИЯ СКОРО ПОЯВИТСЯ!",
                    description=(
                        "Через ~10 минут появится реликвия. "
                        "Вооружайтесь и будьте готовы к бою!"
                    ),
                    color=discord.Color.gold(),
                    timestamp=datetime.now(),
                )
                # Если после рестарта до появления меньше 10 минут — пишем точнее
                remaining_min = max(
                    0,
                    int((appear_at - datetime.now()).total_seconds() // 60),
                )
                if remaining_min < config.RELIC_WARNING_MINUTES:
                    embed.description = (
                        f"Через ~{remaining_min} мин появится реликвия. "
                        "Вооружайтесь и будьте готовы к бою!"
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

                db.set_relic_warning_sent(event_id)
                self._warning_sent = True

            wait_until_end = (appear_at - datetime.now()).total_seconds()
            if wait_until_end > 0:
                await asyncio.sleep(wait_until_end)

            db.finish_relic_event(event_id, "completed")
            self.tasks.pop(self.channel_id, None)
            self.timer_start_time = None
            self.timer_duration = None
            self._event_id = None
            self._warning_sent = False
            action_logger.info(
                f"Relic timer completed for channel ID: {self.channel_id} "
                f"(event_id={event_id})"
            )

        except asyncio.CancelledError:
            # Не сбрасываем состояние, если уже запущен другой event_id
            if self._event_id == event_id:
                self.tasks.pop(self.channel_id, None)
                self.timer_start_time = None
                self.timer_duration = None
                self._event_id = None
                self._warning_sent = False
            action_logger.info(
                f"Relic timer cancelled in channel ID: {self.channel_id} "
                f"(event_id={event_id})"
            )
            raise

    def cancel_timer(self) -> bool:
        """Отменяет активный таймер и помечает событие в БД."""
        had_task = self.channel_id in self.tasks
        had_db = db.cancel_active_relic_event(self.channel_id)

        task = self.tasks.pop(self.channel_id, None)
        self.timer_start_time = None
        self.timer_duration = None
        self._event_id = None
        self._warning_sent = False

        if task is not None:
            task.cancel()

        return had_task or had_db

    def is_active(self) -> bool:
        if self.channel_id in self.tasks:
            return True
        if not self.channel_id:
            return False
        row = db.get_active_relic_event(self.channel_id)
        if row is None:
            return False
        started_at = datetime.fromisoformat(row["started_at"])
        appear_at = started_at + timedelta(minutes=int(row["duration_minutes"]))
        if datetime.now() >= appear_at:
            db.finish_relic_event(int(row["id"]), "completed")
            return False
        return True

    def get_remaining_time(self) -> Optional[float]:
        start = self.timer_start_time
        duration = self.timer_duration
        if start is None or duration is None:
            if not self.channel_id:
                return None
            row = db.get_active_relic_event(self.channel_id)
            if row is None:
                return None
            start = datetime.fromisoformat(row["started_at"])
            duration = int(row["duration_minutes"])

        elapsed = (datetime.now() - start).total_seconds()
        return max(0.0, duration * 60 - elapsed)

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
