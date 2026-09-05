"""Бизнес-логика маяков: расход топлива, проверки, алерты, панель."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import tasks

import config
from services import database as db
from utils.embeds import gray_progress_bar, status_emoji
from utils.formatting import format_priority
from utils.logging_setup import error_logger, system_logger

if TYPE_CHECKING:
    from bot import BeaconBot

_panel_lock = asyncio.Lock()
BEACON_THREAD_NAME = "Локации маяков"


def hours_since(last_updated: str) -> float:
    """Сколько часов прошло с last_updated (ISO)."""
    last_update = datetime.fromisoformat(last_updated)
    return (datetime.now() - last_update).total_seconds() / 3600


def compute_decay(
    current_fuel: float,
    current_lifetime: float,
    fuel_consumption_rate: float,
    hours_passed: float,
) -> tuple[float, float]:
    """Возвращает (new_fuel, new_lifetime) после hours_passed часов."""
    fuel_per_hour = 1.0 / fuel_consumption_rate
    new_fuel = max(0.0, current_fuel - fuel_per_hour * hours_passed)

    if new_fuel <= 0 or current_fuel <= 0:
        lifetime_decay = config.ACCELERATED_DECAY_RATE * hours_passed
    else:
        lifetime_decay = config.LIFETIME_DECAY_RATE * hours_passed

    new_lifetime = max(0.0, current_lifetime - lifetime_decay)
    return new_fuel, new_lifetime


def _alert_channel(bot: BeaconBot) -> discord.abc.Messageable | None:
    if not config.ALERT_CHANNEL_ID:
        return None
    return bot.get_channel(config.ALERT_CHANNEL_ID)


def _beacon_status_embed(
    *,
    title: str,
    beacon_id: str,
    fuel: float,
    lifetime: float,
    color: discord.Color,
    message_link: str | None = None,
) -> discord.Embed:
    fuel_percent = (fuel / config.MAX_FUEL) * 100
    embed = discord.Embed(
        title=title,
        description=f"Маяк **{beacon_id}**",
        color=color,
        timestamp=datetime.now(),
    )
    embed.add_field(
        name=f"{status_emoji(fuel_percent)} Топливо",
        value=(
            f"🛢️ {gray_progress_bar(fuel, config.MAX_FUEL)} "
            f"{fuel:.1f}/{config.MAX_FUEL:.1f}"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"{status_emoji(lifetime)} Прочность",
        value=(
            f"🔧 {gray_progress_bar(lifetime, config.MAX_LIFETIME)} "
            f"{lifetime:.1f}%"
        ),
        inline=False,
    )
    if message_link:
        embed.add_field(name="", value=f"🔗 [Перейти]({message_link})", inline=False)
    return embed


def format_beacon_panel_table(beacons: list[Any]) -> tuple[str, bool]:
    """
    имя · Фронтовой · [Перейти]
    🛢️ bar fuel/max
    🔧 bar lifetime%
    """
    rows: list[str] = []
    has_warning = False

    for beacon in beacons[:25]:
        fuel = float(beacon["current_fuel"])
        lifetime = float(beacon["current_lifetime"])
        fuel_percent = (fuel / config.MAX_FUEL) * 100
        rate = float(beacon["fuel_consumption_rate"])

        if (
            lifetime <= config.WARNING_THRESHOLD
            or fuel_percent <= config.WARNING_THRESHOLD
        ):
            has_warning = True

        if (
            lifetime <= config.CRITICAL_THRESHOLD
            or fuel_percent <= config.CRITICAL_THRESHOLD
        ):
            status_mark = "💀 "
        elif (
            lifetime <= config.WARNING_THRESHOLD
            or fuel_percent <= config.WARNING_THRESHOLD
        ):
            status_mark = "⚠️ "
        else:
            status_mark = ""

        type_label = format_priority(rate)
        header = f"{status_mark}**{beacon['beacon_id']}** · {type_label}"
        if beacon["message_link"]:
            header += f" · [Перейти]({beacon['message_link']})"

        fuel_i = int(round(fuel))
        max_fuel_i = int(round(config.MAX_FUEL))
        life_i = int(round(lifetime))
        # Один пробел после эмодзи — полоски стартуют в одной колонке
        fuel_line = (
            f"🛢️ {gray_progress_bar(fuel, config.MAX_FUEL)} "
            f"{fuel_i}/{max_fuel_i}"
        )
        life_line = (
            f"🔧 {gray_progress_bar(lifetime, config.MAX_LIFETIME)} "
            f"{life_i}%"
        )
        rows.append(f"{header}\n{fuel_line}\n{life_line}")

    return "\n\n".join(rows), has_warning


def build_all_beacons_status_embed() -> discord.Embed:
    """Embed постоянной панели маяков."""
    beacons = db.list_all_beacons()
    if not beacons:
        return discord.Embed(
            title="Панель Маяков",
            description="📭 Нет активных маяков",
            color=discord.Color.dark_grey(),
            timestamp=datetime.now(),
        )

    description, has_warning = format_beacon_panel_table(beacons)
    color = (
        discord.Color.yellow() if has_warning else discord.Color.green()
    )
    embed = discord.Embed(
        title="Панель Маяков",
        description=description,
        color=color,
        timestamp=datetime.now(),
    )

    if len(beacons) > 25:
        embed.set_footer(text=f"Показаны первые 25 из {len(beacons)}")
    return embed


def _panel_channel(
    bot: BeaconBot,
) -> discord.TextChannel | None:
    if not config.PANEL_CHANNEL_ID:
        return None
    channel = bot.get_channel(config.PANEL_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        return channel
    return None


async def _resolve_panel_channel(
    bot: BeaconBot,
) -> discord.TextChannel | None:
    channel = _panel_channel(bot)
    if channel is not None:
        return channel
    if not config.PANEL_CHANNEL_ID:
        return None
    try:
        fetched = await bot.fetch_channel(config.PANEL_CHANNEL_ID)
    except (discord.NotFound, discord.HTTPException) as exc:
        error_logger.error(
            f"Канал панели маяков недоступен: {exc}",
            exc_info=True,
        )
        return None
    if isinstance(fetched, discord.TextChannel):
        return fetched
    return None


async def _ensure_thread_for_message(
    bot: BeaconBot,
    message: discord.Message,
    thread_id: int | None,
) -> discord.Thread | None:
    """Находит или создаёт ветку панели маяков."""
    if thread_id:
        thread = bot.get_channel(thread_id)
        if isinstance(thread, discord.Thread):
            ready = await prepare_thread_for_send(thread)
            if ready is not None:
                return ready
        try:
            fetched = await bot.fetch_channel(thread_id)
            if isinstance(fetched, discord.Thread):
                return await prepare_thread_for_send(fetched)
        except (discord.NotFound, discord.HTTPException):
            pass

    if message.thread is not None:
        return await prepare_thread_for_send(message.thread)

    try:
        thread = await message.create_thread(
            name=BEACON_THREAD_NAME,
            auto_archive_duration=10080,
            reason="Ветка локаций панели маяков",
        )
        return await prepare_thread_for_send(thread)
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось создать ветку панели маяков: {exc}",
            exc_info=True,
        )
        return None


async def prepare_thread_for_send(
    thread: discord.Thread,
) -> discord.Thread | None:
    """Разархивирует ветку и присоединяет бота (иначе часто 403)."""
    try:
        if thread.archived or thread.locked:
            await thread.edit(archived=False, locked=False)
    except discord.Forbidden:
        error_logger.error(
            f"Нет прав разархивировать/разблокировать ветку {thread.id}"
        )
        return None
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось открыть ветку {thread.id}: {exc}",
            exc_info=True,
        )
        return None

    try:
        await thread.join()
    except discord.Forbidden:
        error_logger.error(
            f"Нет прав присоединиться к ветке {thread.id}"
        )
        return None
    except discord.HTTPException:
        # Уже участник / не требуется
        pass

    return thread


async def refresh_beacon_panel(
    bot: BeaconBot,
    *,
    edit_existing: bool = True,
) -> discord.Message | None:
    async with _panel_lock:
        return await _refresh_beacon_panel_locked(
            bot, edit_existing=edit_existing
        )


async def _refresh_beacon_panel_locked(
    bot: BeaconBot,
    *,
    edit_existing: bool = True,
) -> discord.Message | None:
    channel = await _resolve_panel_channel(bot)
    if channel is None:
        return None

    from handlers.views.menu import BeaconPanelView

    embed = build_all_beacons_status_embed()
    view = BeaconPanelView()
    saved = db.get_beacon_panel()

    if saved is not None:
        saved_channel_id, message_id, thread_id = saved
        if saved_channel_id == config.PANEL_CHANNEL_ID:
            try:
                message = await channel.fetch_message(message_id)
                if not edit_existing:
                    return message
                await message.edit(embed=embed, view=view)
                thread = await _ensure_thread_for_message(
                    bot, message, thread_id
                )
                new_thread_id = thread.id if thread else thread_id
                if new_thread_id != thread_id:
                    db.set_beacon_panel(
                        config.PANEL_CHANNEL_ID,
                        message.id,
                        new_thread_id,
                    )
                return message
            except Exception as exc:
                from services.panel_service import is_unknown_message

                if is_unknown_message(exc):
                    db.clear_beacon_panel()
                    system_logger.info(
                        "Beacon panel message missing — will recreate"
                    )
                else:
                    error_logger.error(
                        f"Не удалось обновить панель маяков: {exc}",
                        exc_info=True,
                    )
                    return None
        else:
            db.clear_beacon_panel()

    try:
        message = await channel.send(embed=embed, view=view)
        thread = await _ensure_thread_for_message(bot, message, None)
        db.set_beacon_panel(
            config.PANEL_CHANNEL_ID,
            message.id,
            thread.id if thread else None,
        )
        system_logger.info(
            f"Beacon panel created in channel "
            f"{config.PANEL_CHANNEL_ID} message={message.id} "
            f"thread={thread.id if thread else None}"
        )
        return message
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось создать панель маяков: {exc}",
            exc_info=True,
        )
        return None


async def ensure_beacon_panel(bot: BeaconBot) -> None:
    from handlers.views.menu import BeaconPanelView

    if not getattr(bot, "_beacon_panel_view_registered", False):
        bot.add_view(BeaconPanelView())
        setattr(bot, "_beacon_panel_view_registered", True)
    if not config.PANEL_CHANNEL_ID:
        system_logger.warning(
            "PANEL_CHANNEL_ID не задан — панель маяков отключена"
        )
        return
    await refresh_beacon_panel(bot)


async def get_beacon_panel_thread(bot: BeaconBot) -> discord.Thread | None:
    """Ветка панели для сообщений с локациями маяков."""
    from handlers.views.menu import BeaconPanelView

    if not getattr(bot, "_beacon_panel_view_registered", False):
        bot.add_view(BeaconPanelView())
        setattr(bot, "_beacon_panel_view_registered", True)

    # Не редактируем панель здесь — только наличие сообщения/ветки
    await refresh_beacon_panel(bot, edit_existing=False)
    saved = db.get_beacon_panel()
    if saved is None:
        return None
    _, message_id, thread_id = saved
    channel = await _resolve_panel_channel(bot)
    if channel is None:
        return None
    try:
        message = await channel.fetch_message(message_id)
    except (discord.NotFound, discord.HTTPException):
        await refresh_beacon_panel(bot, edit_existing=False)
        saved = db.get_beacon_panel()
        if saved is None:
            return None
        _, message_id, thread_id = saved
        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.HTTPException):
            return None

    thread = await _ensure_thread_for_message(bot, message, thread_id)
    if thread is not None:
        db.set_beacon_panel(config.PANEL_CHANNEL_ID, message.id, thread.id)
    return thread


def _apply_decay_to_beacon(beacon: Any, now: str) -> tuple[float, float]:
    """Пересчитывает и сохраняет decay. Возвращает (fuel, lifetime)."""
    current_fuel = float(beacon["current_fuel"])
    current_lifetime = float(beacon["current_lifetime"])
    hours_passed = hours_since(beacon["last_updated"])

    if hours_passed <= 0:
        return current_fuel, current_lifetime

    rate = float(beacon["fuel_consumption_rate"])
    new_fuel, new_lifetime = compute_decay(
        current_fuel, current_lifetime, rate, hours_passed
    )

    if current_fuel - new_fuel > 1.5 or current_lifetime - new_lifetime > 5:
        system_logger.debug(
            f"Auto-update beacon {beacon['beacon_id']}: "
            f"Hours passed: {hours_passed:.2f}, "
            f"Fuel: {current_fuel:.1f}→{new_fuel:.1f}, "
            f"Lifetime: {current_lifetime:.1f}→{new_lifetime:.1f}"
        )

    if new_fuel <= 0 or current_fuel <= 0:
        system_logger.debug(
            f"Accelerated decay for beacon {beacon['beacon_id']}: "
            f"no fuel, losing {config.ACCELERATED_DECAY_RATE:.0f}%/hour"
        )

    db.apply_decay_update(beacon["id"], new_fuel, new_lifetime, now)
    return new_fuel, new_lifetime


async def _check_beacon_alerts(
    bot: BeaconBot,
    beacon: Any,
    current_fuel: float,
    current_lifetime: float,
    channel: discord.abc.Messageable | None,
) -> None:
    """Удаление при 0 прочности и алерты по порогам."""
    beacon_id = beacon["beacon_id"]
    try:
        low_status_sent = bool(beacon["low_status_sent"])
    except (KeyError, IndexError):
        low_status_sent = False

    if current_lifetime <= 0:
        reason = (
            "топливо закончилось, маяк разрушился от ускоренного износа"
            if current_fuel <= 0
            else "маяк полностью сгнил"
        )
        if channel:
            await channel.send(
                f"> 🗑️ Маяк **{beacon_id}** удалён — {reason}"
            )
        system_logger.info(f"Auto-deleted beacon {beacon_id}: {reason}")
        db.delete_beacon(beacon_id)
        return

    fuel_percent = (current_fuel / config.MAX_FUEL) * 100
    lifetime_percent = current_lifetime
    send_warning = (
        fuel_percent < config.WARNING_THRESHOLD
        or lifetime_percent < config.WARNING_THRESHOLD
        or (fuel_percent < config.CRITICAL_THRESHOLD and lifetime_percent > 0)
    )

    if send_warning and not low_status_sent:
        is_critical = (
            fuel_percent < config.CRITICAL_THRESHOLD
            or lifetime_percent < config.CRITICAL_THRESHOLD
        )
        warning_emoji = "💀" if is_critical else "⚠️"
        warning_text = "КРИТИЧЕСКИЙ УРОВЕНЬ!" if is_critical else "ВНИМАНИЕ!"
        if channel:
            embed = _beacon_status_embed(
                title=f"{warning_emoji} {warning_text}",
                beacon_id=beacon_id,
                fuel=current_fuel,
                lifetime=current_lifetime,
                color=(
                    discord.Color.red() if is_critical else discord.Color.orange()
                ),
                message_link=beacon["message_link"],
            )
            await channel.send(embed=embed)
        db.set_low_status(beacon_id, True)

    elif (
        low_status_sent
        and fuel_percent >= config.WARNING_THRESHOLD
        and lifetime_percent >= config.WARNING_THRESHOLD
    ):
        db.set_low_status(beacon_id, False)
        if channel:
            embed = _beacon_status_embed(
                title="✅ Маяк восстановил нормальные показатели",
                beacon_id=beacon_id,
                fuel=current_fuel,
                lifetime=current_lifetime,
                color=discord.Color.green(),
                message_link=beacon["message_link"],
            )
            await channel.send(embed=embed)
        system_logger.info(f"Beacon {beacon_id} recovered to normal status")


@tasks.loop(minutes=1)
async def maintain_beacons(bot: BeaconBot) -> None:
    """Один цикл: decay + алерты/удаление (одно чтение таблицы)."""
    try:
        beacons = db.fetch_all_for_update()
        channel = _alert_channel(bot)
        now = datetime.now().isoformat()
        updated_count = 0

        for beacon in beacons:
            hours_passed = hours_since(beacon["last_updated"])
            fuel, lifetime = _apply_decay_to_beacon(beacon, now)
            if hours_passed > 0:
                updated_count += 1
            await _check_beacon_alerts(bot, beacon, fuel, lifetime, channel)

        if updated_count > 0:
            system_logger.debug(
                f"Beacon maintenance completed for {updated_count} beacons"
            )
        await refresh_beacon_panel(bot)
    except Exception as exc:
        error_msg = f"Ошибка в maintain_beacons: {exc}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")
        # Не re-raise: цикл должен продолжать работать после сбоя


@maintain_beacons.before_loop
async def _before_maintain_beacons() -> None:
    await asyncio.sleep(config.BEACON_MAINTAIN_OFFSET_SEC)


def start_background_tasks(bot: BeaconBot) -> None:
    """Запускает фоновый цикл маяков (идемпотентно)."""
    if not maintain_beacons.is_running():
        maintain_beacons.start(bot)


def apply_decay_to_all_beacons() -> int:
    """Ручной пересчёт decay для всех маяков. Возвращает число обновлённых."""
    beacons = db.fetch_all_for_update()
    now = datetime.now().isoformat()
    updated_count = 0
    for beacon in beacons:
        if hours_since(beacon["last_updated"]) > 0:
            _apply_decay_to_beacon(beacon, now)
            updated_count += 1
    return updated_count
