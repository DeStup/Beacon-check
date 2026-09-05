"""Таймер появления реликвии с сохранением в relic_events."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

import config
from services import database as db
from utils.logging_setup import error_logger, relic_logger, system_logger
from utils.relic_embeds import (
    build_relic_panel_embed,
    build_relic_warning_embed,
    relic_qrf_ping_content,
)

if TYPE_CHECKING:
    from bot import BeaconBot

_panel_lock = asyncio.Lock()


def _panel_channel(
    bot: BeaconBot,
) -> discord.TextChannel | discord.Thread | discord.VoiceChannel | None:
    if not config.PANEL_CHANNEL_ID:
        return None
    channel = bot.get_channel(config.PANEL_CHANNEL_ID)
    if not isinstance(
        channel,
        (discord.TextChannel, discord.Thread, discord.VoiceChannel),
    ):
        return None
    return channel


async def refresh_relic_panel(bot: BeaconBot) -> discord.Message | None:
    """Обновляет или создаёт сообщение панели реликвии в PANEL_CHANNEL_ID."""
    async with _panel_lock:
        return await _refresh_relic_panel_locked(bot)


async def _refresh_relic_panel_locked(
    bot: BeaconBot,
) -> discord.Message | None:
    channel = _panel_channel(bot)
    if channel is None and config.PANEL_CHANNEL_ID:
        try:
            fetched = await bot.fetch_channel(config.PANEL_CHANNEL_ID)
        except (discord.NotFound, discord.HTTPException) as exc:
            error_logger.error(
                f"Канал панели реликвии недоступен: {exc}",
                exc_info=True,
            )
            return None
        if not isinstance(
            fetched,
            (discord.TextChannel, discord.Thread, discord.VoiceChannel),
        ):
            return None
        channel = fetched
    if channel is None:
        return None

    from handlers.views.relic_views import relic_panel_view_for

    timer = bot.relic_timer
    active = timer.is_active()
    embed = build_relic_panel_embed(timer)
    view = relic_panel_view_for(active)
    saved = db.get_relic_panel()

    if saved is not None:
        saved_channel_id, message_id = saved
        if saved_channel_id == config.PANEL_CHANNEL_ID:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return message
            except Exception as exc:
                from services.panel_service import is_unknown_message

                if is_unknown_message(exc):
                    db.clear_relic_panel()
                    system_logger.info(
                        "Relic panel message missing — will recreate"
                    )
                else:
                    error_logger.error(
                        f"Не удалось обновить панель реликвии: {exc}",
                        exc_info=True,
                    )
                    return None
        else:
            db.clear_relic_panel()

    try:
        message = await channel.send(embed=embed, view=view)
        db.set_relic_panel(config.PANEL_CHANNEL_ID, message.id)
        system_logger.info(
            f"Relic panel created in channel "
            f"{config.PANEL_CHANNEL_ID} message={message.id}"
        )
        return message
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось создать панель реликвии: {exc}",
            exc_info=True,
        )
        return None


async def ensure_relic_panel(bot: BeaconBot) -> None:
    """Регистрирует persistent views и синхронизирует панель при старте."""
    from handlers.views.relic_views import (
        RelicPanelActiveView,
        RelicPanelIdleView,
    )

    if not getattr(bot, "_relic_panel_view_registered", False):
        bot.add_view(RelicPanelIdleView())
        bot.add_view(RelicPanelActiveView())
        setattr(bot, "_relic_panel_view_registered", True)
    if not config.PANEL_CHANNEL_ID:
        system_logger.warning(
            "PANEL_CHANNEL_ID не задан — панель реликвии отключена"
        )
        return
    await refresh_relic_panel(bot)


class RelicTimer:
    """Управление asyncio-таймером реликвии для одного канала."""

    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self.timer_start_time: Optional[datetime] = None
        self.timer_duration: Optional[int] = None
        self.started_by: Optional[str] = None
        self._event_id: Optional[int] = None
        self._warning_sent: bool = False
        self._hold_until: Optional[datetime] = None

    def _clear_runtime_state(self) -> None:
        self.timer_start_time = None
        self.timer_duration = None
        self.started_by = None
        self._event_id = None
        self._warning_sent = False
        self._hold_until = None

    async def start_timer(
        self,
        bot: BeaconBot,
        minutes: int = config.DEFAULT_RELIC_MINUTES,
        *,
        user_info: Optional[str] = None,
        started_by: Optional[str] = None,
        restarted: bool = False,
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
            started_by=started_by,
        )

        self.timer_start_time = started_at
        self.timer_duration = minutes
        self.started_by = started_by
        self._event_id = event_id
        self._warning_sent = False
        self._hold_until = None

        task = asyncio.create_task(self._run_timer(bot))
        self.tasks[self.channel_id] = task

        action_word = "restarted" if restarted else "started"
        user_prefix = f"{user_info} | " if user_info else ""
        channel_name = getattr(channel, "name", str(self.channel_id))
        log = relic_logger if user_info else system_logger
        log.info(
            f"{user_prefix}Relic timer {action_word} in channel {channel_name} "
            f"(ID: {self.channel_id}) for {minutes} minutes "
            f"(event_id={event_id})"
        )
        await refresh_relic_panel(bot)
        return task

    async def restore(self, bot: BeaconBot) -> bool:
        """Восстанавливает активный таймер из БД после рестарта. True если подняли."""
        if not self.channel_id:
            return False

        existing = self.tasks.get(self.channel_id)
        if existing is not None and not existing.done():
            system_logger.debug(
                f"Relic timer already running for channel {self.channel_id}; "
                "skip restore"
            )
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
            system_logger.info(
                f"Relic event {row['id']} already expired on restore; marked completed"
            )
            return False

        self.timer_start_time = started_at
        self.timer_duration = duration
        self._event_id = int(row["id"])
        self._warning_sent = bool(row["warning_sent"])
        self.started_by = row["started_by"] if "started_by" in row.keys() else None
        self._hold_until = None

        if existing is not None:
            existing.cancel()

        task = asyncio.create_task(self._run_timer(bot))
        self.tasks[self.channel_id] = task

        remaining = (appear_at - now).total_seconds()
        system_logger.info(
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
                    self._clear_runtime_state()
                    await refresh_relic_panel(bot)
                    return

                unix_timestamp = int(appear_at.timestamp())
                embed = build_relic_warning_embed(
                    unix_timestamp,
                    started_by=self.started_by,
                )
                await channel.send(
                    content=relic_qrf_ping_content(),
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )

                db.set_relic_warning_sent(event_id)
                self._warning_sent = True
                system_logger.info(
                    f"Relic warning sent to channel ID {self.channel_id} "
                    f"(event_id={event_id})"
                )
                await refresh_relic_panel(bot)

            wait_until_end = (appear_at - datetime.now()).total_seconds()
            if wait_until_end > 0:
                await asyncio.sleep(wait_until_end)

            db.finish_relic_event(event_id, "completed")
            self._hold_until = datetime.now() + timedelta(
                minutes=config.RELIC_PANEL_HOLD_MINUTES
            )
            system_logger.info(
                f"Relic timer completed for channel ID: {self.channel_id} "
                f"(event_id={event_id}); panel hold "
                f"{config.RELIC_PANEL_HOLD_MINUTES}m"
            )
            await refresh_relic_panel(bot)

            hold_left = (self._hold_until - datetime.now()).total_seconds()
            if hold_left > 0:
                await asyncio.sleep(hold_left)

            if self._event_id == event_id:
                self.tasks.pop(self.channel_id, None)
                self._clear_runtime_state()
                await refresh_relic_panel(bot)

        except asyncio.CancelledError:
            if self._event_id == event_id:
                self.tasks.pop(self.channel_id, None)
                self._clear_runtime_state()
            system_logger.debug(
                f"Relic timer task cancelled internally "
                f"(channel_id={self.channel_id}, event_id={event_id})"
            )
            raise

    def cancel_timer(
        self,
        *,
        user_info: Optional[str] = None,
        log: bool = True,
    ) -> bool:
        """Отменяет активный таймер и помечает событие в БД."""
        had_task = self.channel_id in self.tasks
        had_hold = self._hold_until is not None
        had_db = db.cancel_active_relic_event(self.channel_id)

        task = self.tasks.pop(self.channel_id, None)
        self._clear_runtime_state()

        if task is not None:
            task.cancel()

        cancelled = had_task or had_db or had_hold
        if cancelled and log:
            user_prefix = f"{user_info} | " if user_info else ""
            log_fn = relic_logger if user_info else system_logger
            log_fn.info(
                f"{user_prefix}Relic timer cancelled "
                f"(channel_id={self.channel_id})"
            )
        return cancelled

    def is_holding(self) -> bool:
        """Таймер завершён, но ещё отображается на панели."""
        if self._hold_until is None:
            return False
        return datetime.now() < self._hold_until

    def is_active(self) -> bool:
        if self.is_holding():
            return False
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
        if self.is_holding():
            return 0.0
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
        if self.is_holding():
            return "Появилась"
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
