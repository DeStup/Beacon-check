"""Логика сезонов: цикл 24ч, панель и алерты."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord

import config
from services import database as db
from utils.logging_setup import error_logger, season_logger, system_logger

if TYPE_CHECKING:
    from bot import BeaconBot

_panel_lock = asyncio.Lock()
_watch_task: asyncio.Task[None] | None = None
_watch_lock = asyncio.Lock()


def normalize_season_key(raw: str) -> str:
    key = raw.strip().lower()
    if key not in config.SEASON_KEYS:
        raise ValueError(f"Неизвестный сезон: {raw}")
    return key


def season_label(key: str) -> str:
    """Название сезона с иконкой."""
    emoji = config.SEASON_EMOJIS.get(key, "")
    name = config.SEASON_LABELS.get(key, key)
    if emoji:
        return f"{emoji} {name}"
    return name


def next_season_key(current: str) -> str:
    keys = config.SEASON_KEYS
    idx = keys.index(normalize_season_key(current))
    return keys[(idx + 1) % len(keys)]


def season_ends_at(started_at: datetime) -> datetime:
    return started_at + timedelta(hours=config.SEASON_DURATION_HOURS)


def daynight_snapshot(
    started_at: datetime,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Фаза дня/ночи относительно started_at сезона.
    Цикл 60 мин: 0–45 день, 45–60 ночь.
    """
    if now is None:
        now = datetime.now()
    cycle_sec = config.DAY_CYCLE_MINUTES * 60
    day_sec = config.DAYLIGHT_MINUTES * 60
    night_sec = config.NIGHT_MINUTES * 60
    elapsed = max(0.0, (now - started_at).total_seconds())
    pos = elapsed % cycle_sec

    if pos < day_sec:
        is_day = True
        into_phase = pos
        phase_left = day_sec - pos
        # Игровое время: 03:00 → 21:00 за 45 реальных минут
        game_span_min = 18 * 60
        game_min = 3 * 60 + (into_phase / day_sec) * game_span_min
    else:
        is_day = False
        into_phase = pos - day_sec
        phase_left = cycle_sec - pos
        # Игровое время: 21:00 → 03:00 (+1д) за 15 реальных минут
        game_span_min = 6 * 60
        game_min = 21 * 60 + (into_phase / night_sec) * game_span_min

    game_min = int(game_min) % (24 * 60)
    game_h, game_m = divmod(game_min, 60)
    phase_ends = now + timedelta(seconds=phase_left)

    if is_day:
        label = "☀️ День"
    else:
        label = "🌙 Ночь"

    return {
        "is_day": is_day,
        "label": label,
        "game_time": f"{game_h:02d}:{game_m:02d}",
        "phase_ends_at": phase_ends,
        "seconds_left": phase_left,
    }


def compute_started_at(*, elapsed_minutes: int = 0) -> datetime:
    """Момент старта текущего сезона с учётом уже прошедшего времени."""
    if elapsed_minutes < 0:
        raise ValueError("Прошедшее время не может быть отрицательным")
    if elapsed_minutes > config.SEASON_DURATION_MINUTES:
        raise ValueError(
            f"Прошедшее время не больше "
            f"{config.SEASON_DURATION_MINUTES} мин "
            f"({config.SEASON_DURATION_HOURS:g} ч)"
        )
    return datetime.now() - timedelta(minutes=elapsed_minutes)


def snapshot_season(row: Any | None = None) -> dict[str, Any] | None:
    """Актуальный снимок сезона (без записи в БД)."""
    if row is None:
        row = db.get_season_state()
    if row is None:
        return None

    key = normalize_season_key(str(row["season_key"]))
    started = datetime.fromisoformat(str(row["started_at"]))
    now = datetime.now()
    duration = timedelta(hours=config.SEASON_DURATION_HOURS)

    while started + duration <= now:
        key = next_season_key(key)
        started = started + duration

    return {
        "season_key": key,
        "label": season_label(key),
        "started_at": started,
        "ends_at": season_ends_at(started),
        "daynight": daynight_snapshot(started, now=now),
    }


def build_season_panel_embed(
    snap: dict[str, Any] | None,
) -> discord.Embed:
    if snap is None:
        return discord.Embed(
            title="Время",
            description=(
                "Сезон не настроен.\n"
                "Используйте `/season setup`, чтобы задать текущий сезон."
            ),
            color=discord.Color.dark_grey(),
            timestamp=datetime.now(),
        )

    ends_unix = int(snap["ends_at"].timestamp())
    dn = snap["daynight"]
    phase_unix = int(dn["phase_ends_at"].timestamp())
    color = discord.Color(
        config.SEASON_COLORS.get(
            snap["season_key"],
            discord.Color.orange().value,
        )
    )
    embed = discord.Embed(
        title="Время",
        color=color,
        timestamp=datetime.now(),
    )
    embed.add_field(
        name="Сезон",
        value=snap["label"],
        inline=False,
    )
    embed.add_field(
        name="Следующий сезон наступит",
        value=f"<t:{ends_unix}:f> (<t:{ends_unix}:R>)",
        inline=False,
    )
    embed.add_field(
        name="Время суток",
        value=(
            f"{dn['label']}\n"
            f"До смены: <t:{phase_unix}:R>"
        ),
        inline=False,
    )
    return embed


def build_season_alert_embed(snap: dict[str, Any]) -> discord.Embed:
    ends_unix = int(snap["ends_at"].timestamp())
    return discord.Embed(
        title="Новый сезон",
        description=f"Начался **`{snap['label']}`**",
        color=discord.Color(
            config.SEASON_COLORS.get(
                snap["season_key"],
                discord.Color.gold().value,
            )
        ),
        timestamp=datetime.now(),
    ).add_field(
        name="Закончится",
        value=f"<t:{ends_unix}:f> (<t:{ends_unix}:R>)",
        inline=False,
    )


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


async def refresh_season_panel(
    bot: BeaconBot,
    *,
    edit_existing: bool = True,
) -> discord.Message | None:
    async with _panel_lock:
        return await _refresh_season_panel_locked(
            bot, edit_existing=edit_existing
        )


async def _refresh_season_panel_locked(
    bot: BeaconBot,
    *,
    edit_existing: bool = True,
) -> discord.Message | None:
    channel = _panel_channel(bot)
    if channel is None and config.PANEL_CHANNEL_ID:
        try:
            fetched = await bot.fetch_channel(config.PANEL_CHANNEL_ID)
        except (discord.NotFound, discord.HTTPException) as exc:
            error_logger.error(
                f"Канал панели сезонов недоступен: {exc}",
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

    snap = snapshot_season()
    embed = build_season_panel_embed(snap)
    saved = db.get_season_panel()

    if saved is not None:
        saved_channel_id, message_id = saved
        if saved_channel_id == config.PANEL_CHANNEL_ID:
            try:
                message = await channel.fetch_message(message_id)
                if not edit_existing:
                    return message
                await message.edit(embed=embed, view=None)
                return message
            except Exception as exc:
                from services.panel_service import is_unknown_message

                if is_unknown_message(exc):
                    db.clear_season_panel()
                    system_logger.info(
                        "Season panel message missing — will recreate"
                    )
                else:
                    error_logger.error(
                        f"Не удалось обновить панель сезонов: {exc}",
                        exc_info=True,
                    )
                    return None
        else:
            db.clear_season_panel()

    try:
        message = await channel.send(embed=embed)
        db.set_season_panel(config.PANEL_CHANNEL_ID, message.id)
        system_logger.info(
            f"Season panel created in channel "
            f"{config.PANEL_CHANNEL_ID} message={message.id}"
        )
        return message
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось создать панель сезонов: {exc}",
            exc_info=True,
        )
        return None


async def ensure_season_panel(bot: BeaconBot) -> None:
    if not config.PANEL_CHANNEL_ID:
        system_logger.warning(
            "PANEL_CHANNEL_ID не задан — панель сезонов отключена"
        )
        return
    await refresh_season_panel(bot)


async def _send_season_alert(
    bot: BeaconBot,
    snap: dict[str, Any],
) -> None:
    if not config.SEASON_ALERT_CHANNEL_ID:
        return
    channel = bot.get_channel(config.SEASON_ALERT_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(config.SEASON_ALERT_CHANNEL_ID)
        except (discord.NotFound, discord.HTTPException) as exc:
            error_logger.error(
                f"Канал SEASON_ALERT_CHANNEL_ID недоступен: {exc}",
                exc_info=True,
            )
            return
    if not isinstance(channel, discord.abc.Messageable):
        return
    try:
        await channel.send(embed=build_season_alert_embed(snap))
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось отправить алерт сезона: {exc}",
            exc_info=True,
        )


def setup_season(
    season_key: str,
    *,
    elapsed_minutes: int = 0,
) -> dict[str, Any]:
    key = normalize_season_key(season_key)
    started = compute_started_at(elapsed_minutes=elapsed_minutes)
    db.set_season_state(key, started.isoformat())
    snap = snapshot_season()
    assert snap is not None
    return snap


def clear_season() -> bool:
    """Сбрасывает таймер сезонов. True если состояние было."""
    had = db.get_season_state() is not None
    db.clear_season_state()
    return had


async def advance_due_seasons(bot: BeaconBot) -> int:
    """
    Проматывает завершённые сезоны, шлёт алерт на каждый новый,
    обновляет панель. Возвращает число смен.
    """
    row = db.get_season_state()
    if row is None:
        return 0

    key = normalize_season_key(str(row["season_key"]))
    started = datetime.fromisoformat(str(row["started_at"]))
    now = datetime.now()
    duration = timedelta(hours=config.SEASON_DURATION_HOURS)
    advanced = 0

    while started + duration <= now:
        key = next_season_key(key)
        started = started + duration
        db.set_season_state(key, started.isoformat())
        snap = {
            "season_key": key,
            "label": season_label(key),
            "started_at": started,
            "ends_at": season_ends_at(started),
        }
        await _send_season_alert(bot, snap)
        season_logger.info(f"Season advanced → {key}")
        advanced += 1

    if advanced:
        await refresh_season_panel(bot)
    return advanced


async def _season_watch_loop(bot: BeaconBot) -> None:
    """Спит до смены сезона или дня/ночи; алерты только при смене сезона."""
    try:
        while True:
            row = db.get_season_state()
            if row is None:
                await asyncio.sleep(30)
                continue

            snap = snapshot_season(row)
            if snap is None:
                await asyncio.sleep(30)
                continue

            now = datetime.now()
            season_delay = (snap["ends_at"] - now).total_seconds()
            phase_delay = (
                snap["daynight"]["phase_ends_at"] - now
            ).total_seconds()
            delay = min(season_delay, phase_delay)

            if delay > 0:
                system_logger.debug(
                    f"Season watch sleeping {delay:.1f}s "
                    f"(season={season_delay:.1f}s, "
                    f"daynight={phase_delay:.1f}s)"
                )
                await asyncio.sleep(delay)

            try:
                advanced = await advance_due_seasons(bot)
                # панель всегда: смена дня/ночи или сезона
                await refresh_season_panel(bot)
                if advanced == 0 and delay <= 0:
                    await asyncio.sleep(1)
            except Exception as exc:
                error_msg = f"Ошибка в season watch: {exc}"
                error_logger.error(error_msg, exc_info=True)
                print(f"[ОШИБКА] {error_msg}")
                await asyncio.sleep(5)
    except asyncio.CancelledError:
        system_logger.debug("Season watch loop cancelled")
        raise


async def restart_season_watcher(bot: BeaconBot) -> None:
    """Перезапускает ожидание смены сезона / дня-ночи."""
    global _watch_task
    async with _watch_lock:
        if _watch_task is not None and not _watch_task.done():
            _watch_task.cancel()
            try:
                await _watch_task
            except asyncio.CancelledError:
                pass
        _watch_task = asyncio.create_task(
            _season_watch_loop(bot),
            name="season_watch",
        )


def start_season_tasks(bot: BeaconBot) -> None:
    asyncio.create_task(restart_season_watcher(bot), name="season_watch_start")
