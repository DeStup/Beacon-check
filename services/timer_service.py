"""Пользовательские таймеры с сохранением в таблице timers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

from services import database as db
from utils.logging_setup import error_logger, system_logger, timer_logger

if TYPE_CHECKING:
    from bot import BeaconBot


class TimerManager:
    """Несколько независимых asyncio-таймеров."""

    def __init__(self) -> None:
        self.tasks: dict[int, asyncio.Task[None]] = {}

    async def add_timer(
        self,
        bot: BeaconBot,
        *,
        name: str,
        duration_seconds: int,
        warning_minutes: int,
        created_by_id: int,
        created_by_name: str,
        channel_id: int,
        guild_id: Optional[int] = None,
        user_info: Optional[str] = None,
    ) -> tuple[int, datetime]:
        """Создаёт таймер в БД и запускает задачу. Возвращает (id, trigger_at)."""
        created_at = datetime.now()
        trigger_at = created_at + timedelta(seconds=duration_seconds)
        timer_id = db.create_timer(
            name=name,
            created_at=created_at,
            trigger_at=trigger_at,
            created_by_id=created_by_id,
            created_by_name=created_by_name,
            channel_id=channel_id,
            warning_minutes=warning_minutes,
            guild_id=guild_id,
        )
        self._spawn(bot, timer_id, trigger_at, warning_minutes, notified=False)

        user_prefix = f"{user_info} | " if user_info else ""
        log = timer_logger if user_info else system_logger
        log.info(
            f"{user_prefix}Timer created id={timer_id} name={name!r} "
            f"duration={duration_seconds}s warn={warning_minutes}m "
            f"trigger_at={trigger_at.isoformat()} channel_id={channel_id}"
        )
        return timer_id, trigger_at

    async def cancel(
        self,
        timer_id: int,
        *,
        user_info: Optional[str] = None,
    ) -> bool:
        """Отменяет активный таймер. True если был активен."""
        cancelled = db.cancel_timer(timer_id)
        task = self.tasks.pop(timer_id, None)
        if task is not None and not task.done():
            task.cancel()

        if cancelled:
            user_prefix = f"{user_info} | " if user_info else ""
            log = timer_logger if user_info else system_logger
            log.info(f"{user_prefix}Timer cancelled id={timer_id}")
        return cancelled

    async def restore_all(self, bot: BeaconBot) -> int:
        """Поднимает активные таймеры из БД после рестарта. Возвращает число."""
        restored = 0
        now = datetime.now()
        for row in db.list_active_timers():
            timer_id = int(row["id"])
            trigger_at = datetime.fromisoformat(row["trigger_at"])
            warning_minutes = (
                int(row["warning_minutes"])
                if "warning_minutes" in row.keys()
                else 0
            )
            notified = (
                bool(row["warning_sent"])
                if "warning_sent" in row.keys()
                else False
            )

            if now >= trigger_at:
                if not notified:
                    await self._notify(bot, row)
                    db.set_timer_warning_sent(timer_id)
                db.finish_timer(timer_id, "completed")
                system_logger.info(
                    f"Timer {timer_id} already expired on restore; marked completed"
                )
                continue

            existing = self.tasks.get(timer_id)
            if existing is not None and not existing.done():
                continue

            self._spawn(
                bot,
                timer_id,
                trigger_at,
                warning_minutes,
                notified=notified,
            )
            restored += 1
            remaining = (trigger_at - now).total_seconds()
            system_logger.info(
                f"Timer restored id={timer_id} name={row['name']!r}, "
                f"remaining ~{int(remaining)}s warn={warning_minutes}m "
                f"notified={notified}"
            )
        return restored

    def _spawn(
        self,
        bot: BeaconBot,
        timer_id: int,
        trigger_at: datetime,
        warning_minutes: int,
        *,
        notified: bool,
    ) -> None:
        existing = self.tasks.pop(timer_id, None)
        if existing is not None and not existing.done():
            existing.cancel()
        self.tasks[timer_id] = asyncio.create_task(
            self._run(
                bot,
                timer_id,
                trigger_at,
                warning_minutes,
                notified=notified,
            )
        )

    async def _run(
        self,
        bot: BeaconBot,
        timer_id: int,
        trigger_at: datetime,
        warning_minutes: int,
        *,
        notified: bool,
    ) -> None:
        """Одно уведомление: за warn минут до конца, либо в момент окончания."""
        try:
            notify_at = trigger_at
            if warning_minutes > 0:
                notify_at = trigger_at - timedelta(minutes=warning_minutes)

            if not notified:
                wait_until_notify = (notify_at - datetime.now()).total_seconds()
                if wait_until_notify > 0:
                    await asyncio.sleep(wait_until_notify)

                row = db.get_timer(timer_id)
                if row is None or row["status"] != "active":
                    self.tasks.pop(timer_id, None)
                    return

                await self._notify(bot, row)
                db.set_timer_warning_sent(timer_id)
                system_logger.info(
                    f"Timer notified id={timer_id} "
                    f"warn={warning_minutes}m"
                )

            wait_until_end = (trigger_at - datetime.now()).total_seconds()
            if wait_until_end > 0:
                await asyncio.sleep(wait_until_end)

            row = db.get_timer(timer_id)
            if row is None or row["status"] != "active":
                self.tasks.pop(timer_id, None)
                return

            finished = db.finish_timer(timer_id, "completed")
            self.tasks.pop(timer_id, None)
            if finished:
                system_logger.info(
                    f"Timer completed id={timer_id} name={row['name']!r}"
                )

        except asyncio.CancelledError:
            self.tasks.pop(timer_id, None)
            raise

    async def _resolve_user(
        self,
        bot: BeaconBot,
        row: db.Row,
    ) -> Optional[discord.User]:
        user = bot.get_user(int(row["created_by_id"]))
        if user is not None:
            return user
        try:
            return await bot.fetch_user(int(row["created_by_id"]))
        except Exception:
            error_logger.error(
                f"User {row['created_by_id']} not found for timer {row['id']}"
            )
            return None

    async def _notify(
        self,
        bot: BeaconBot,
        row: db.Row,
    ) -> None:
        user = await self._resolve_user(bot, row)
        if user is None:
            return

        trigger_at = datetime.fromisoformat(row["trigger_at"])
        unix_ts = int(trigger_at.timestamp())
        embed = discord.Embed(
            description=str(row["name"]),
            color=discord.Color.blurple(),
            timestamp=datetime.now(),
        )
        embed.add_field(
            name="Время",
            value=f"<t:{unix_ts}:f> (<t:{unix_ts}:R>)",
            inline=False,
        )
        try:
            await user.send(embed=embed)
        except Exception:
            error_logger.exception(
                f"Failed to DM timer id={row['id']} "
                f"user_id={row['created_by_id']}"
            )
