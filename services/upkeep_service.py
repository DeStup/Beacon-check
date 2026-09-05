"""Бизнес-логика upkeep: расход серебра и предупреждения."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import tasks

import config
from services import database as db
from services.beacon_service import hours_since
from utils.formatting import format_duration_hours
from utils.logging_setup import error_logger, system_logger

if TYPE_CHECKING:
    from bot import BeaconBot

_panel_lock = asyncio.Lock()


def display_silver_rate(rate: float) -> int:
    """Расход для UI: округление вверх."""
    if rate <= 0:
        return 0
    return math.ceil(rate)


def display_silver_amount(amount: float) -> int:
    """Запас для UI: округление вниз."""
    if amount <= 0:
        return 0
    return math.floor(amount)


def compute_current_silver(
    silver_amount: float,
    silver_per_hour: float,
    last_updated: str,
) -> float:
    """Актуальный запас серебра с учётом прошедшего времени."""
    hours_passed = hours_since(last_updated)
    if hours_passed <= 0 or silver_per_hour <= 0:
        return max(0.0, silver_amount)
    return max(0.0, silver_amount - silver_per_hour * hours_passed)


def hours_remaining(silver: float, silver_per_hour: float) -> float:
    if silver_per_hour <= 0:
        return float("inf") if silver > 0 else 0.0
    return silver / silver_per_hour


def apply_decay_to_upkeep(row: Any) -> tuple[float, float]:
    """Пересчитывает и сохраняет запас. Возвращает (silver, hours_left)."""
    amount = float(row["silver_amount"])
    rate = float(row["silver_per_hour"])
    current = compute_current_silver(amount, rate, row["last_updated"])
    hours_passed = hours_since(row["last_updated"])
    if hours_passed > 0:
        db.apply_upkeep_decay_update(
            int(row["id"]),
            current,
            datetime.now().isoformat(),
        )
    return current, hours_remaining(current, rate)


def apply_decay_to_all_upkeep() -> int:
    rows = db.fetch_all_upkeep_for_update()
    updated = 0
    for row in rows:
        if hours_since(row["last_updated"]) > 0:
            apply_decay_to_upkeep(row)
            updated += 1
    return updated


def snapshot_upkeep(row: Any) -> dict[str, Any]:
    """Актуальные поля объекта без обязательной записи в БД."""
    amount = float(row["silver_amount"])
    rate = float(row["silver_per_hour"])
    current = compute_current_silver(amount, rate, row["last_updated"])
    left = hours_remaining(current, rate)
    try:
        warned = bool(row["low_warning_sent"])
    except (KeyError, IndexError):
        warned = False
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "silver_per_hour": rate,
        "silver_amount": current,
        "hours_left": left,
        "low_warning_sent": warned,
    }


def format_hours_left_display(hours_left: float) -> str:
    if hours_left == float("inf"):
        return "∞ (расход 0)"
    if hours_left <= 0:
        return "гниёт"
    text = format_duration_hours(hours_left)
    deplete_at = datetime.now() + timedelta(hours=hours_left)
    unix = int(deplete_at.timestamp())
    return f"{text} (<t:{unix}:R>)"


def format_upkeep_status_table(snaps: list[dict[str, Any]]) -> str:
    """Список объектов для embed — без колонок, читается на телефоне."""
    lines: list[str] = []
    for snap in snaps:
        name = str(snap["name"])
        if snap["hours_left"] < config.UPKEEP_WARNING_HOURS:
            mark = "⚠️ "
        else:
            mark = ""
        rate = display_silver_rate(snap["silver_per_hour"])
        stock = display_silver_amount(snap["silver_amount"])
        if stock == 0:
            time_part = "💀`гниёт`"
        elif snap["hours_left"] == float("inf"):
            time_part = "⏳`∞`"
        else:
            left = format_duration_hours(snap["hours_left"])
            time_part = f"⏳`{left}`"
        lines.append(
            f"{mark}**{name}**\n"
            f"{config.SILVER_EMOJI}`{stock}`"
            f"\u2003⬇️`{rate}`/ч"
            f"\u2003{time_part}"
        )
    return "\n".join(lines)


def build_upkeep_status_embed(
    *,
    title: str,
    name: str,
    silver_amount: float,
    silver_per_hour: float,
    hours_left: float,
    color: discord.Color,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=f"**{name}**",
        color=color,
        timestamp=datetime.now(),
    )
    embed.add_field(
        name=f"{config.SILVER_EMOJI} Склад",
        value=f"{display_silver_amount(silver_amount)} серебра",
        inline=True,
    )
    embed.add_field(
        name="Содержание",
        value=f"{display_silver_rate(silver_per_hour)} серебра/час",
        inline=True,
    )
    left_name = "⏳ Хватит на"
    if 0 < hours_left < config.UPKEEP_WARNING_HOURS:
        left_name = "⚠️ Хватит на"
    elif hours_left <= 0:
        left_name = "💀 Статус"
    embed.add_field(
        name=left_name,
        value=format_hours_left_display(hours_left),
        inline=False,
    )
    return embed


def build_all_upkeep_status_embed() -> discord.Embed:
    rows = db.list_all_upkeep()
    embed = discord.Embed(
        title="Панель Владений Новгорода",
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )
    if not rows:
        embed.description = "📭 Нет объектов содержания"
        return embed

    snaps = [snapshot_upkeep(row) for row in rows[:25]]
    embed.description = format_upkeep_status_table(snaps)
    return embed


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


async def refresh_upkeep_panel(bot: BeaconBot) -> discord.Message | None:
    """Обновляет или создаёт сообщение панели Владений Новгорода в канале."""
    async with _panel_lock:
        return await _refresh_upkeep_panel_locked(bot)


async def _refresh_upkeep_panel_locked(
    bot: BeaconBot,
) -> discord.Message | None:
    channel = _panel_channel(bot)
    if channel is None and config.PANEL_CHANNEL_ID:
        try:
            fetched = await bot.fetch_channel(config.PANEL_CHANNEL_ID)
        except (discord.NotFound, discord.HTTPException) as exc:
            error_logger.error(
                f"Канал панели Владений Новгорода недоступен: {exc}",
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

    from handlers.views.upkeep_views import UpkeepMenuView

    embed = build_all_upkeep_status_embed()
    view = UpkeepMenuView()
    saved = db.get_upkeep_panel()

    if saved is not None:
        saved_channel_id, message_id = saved
        if saved_channel_id == config.PANEL_CHANNEL_ID:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return message
            except discord.NotFound:
                db.clear_upkeep_panel()
            except discord.HTTPException as exc:
                error_logger.error(
                    f"Не удалось обновить панель Владений Новгорода: {exc}",
                    exc_info=True,
                )
                return None
        else:
            db.clear_upkeep_panel()

    try:
        message = await channel.send(embed=embed, view=view)
        db.set_upkeep_panel(config.PANEL_CHANNEL_ID, message.id)
        system_logger.info(
            f"Upkeep panel created in channel "
            f"{config.PANEL_CHANNEL_ID} message={message.id}"
        )
        return message
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось создать панель Владений Новгорода: {exc}",
            exc_info=True,
        )
        return None


async def ensure_upkeep_panel(bot: BeaconBot) -> None:
    """Регистрирует persistent view и синхронизирует панель при старте."""
    from handlers.views.upkeep_views import UpkeepMenuView

    if not getattr(bot, "_upkeep_panel_view_registered", False):
        bot.add_view(UpkeepMenuView())
        setattr(bot, "_upkeep_panel_view_registered", True)
    if not config.PANEL_CHANNEL_ID:
        system_logger.warning(
            "PANEL_CHANNEL_ID не задан — панель Владений Новгорода отключена"
        )
        return
    await refresh_upkeep_panel(bot)


def _alert_channel(bot: BeaconBot) -> discord.abc.Messageable | None:
    if not config.UPKEEP_ALERT_CHANNEL_ID:
        return None
    return bot.get_channel(config.UPKEEP_ALERT_CHANNEL_ID)


async def _check_upkeep_alerts(
    bot: BeaconBot,
    row: Any,
    silver: float,
    hours_left: float,
    channel: discord.abc.Messageable | None,
) -> None:
    object_id = int(row["id"])
    name = row["name"]
    rate = float(row["silver_per_hour"])
    try:
        warned = bool(row["low_warning_sent"])
    except (KeyError, IndexError):
        warned = False

    low = hours_left < config.UPKEEP_WARNING_HOURS

    if low and not warned:
        if channel:
            if hours_left <= 0:
                await channel.send(
                    f"💀 Закончилось серебро у **{name}**"
                )
            else:
                deplete_at = datetime.now() + timedelta(hours=hours_left)
                unix = int(deplete_at.timestamp())
                await channel.send(
                    f"⚠️ Мало серебра на содержание у **{name}**, "
                    f"закончится (<t:{unix}:R>)"
                )
        db.set_upkeep_low_warning(object_id, True)
        system_logger.info(
            f"Upkeep warning sent for {name} "
            f"(hours_left={hours_left:.2f})"
        )
    elif (
        warned
        and hours_left >= config.UPKEEP_WARNING_HOURS
    ):
        db.set_upkeep_low_warning(object_id, False)
        if channel:
            embed = build_upkeep_status_embed(
                title="✅ Содержание восстановлено",
                name=name,
                silver_amount=silver,
                silver_per_hour=rate,
                hours_left=hours_left,
                color=discord.Color.green(),
            )
            await channel.send(embed=embed)
        system_logger.info(f"Upkeep {name} recovered above warning threshold")


@tasks.loop(minutes=1)
async def maintain_upkeep(bot: BeaconBot) -> None:
    try:
        rows = db.fetch_all_upkeep_for_update()
        channel = _alert_channel(bot)
        updated = 0
        for row in rows:
            hours_passed = hours_since(row["last_updated"])
            silver, left = apply_decay_to_upkeep(row)
            if hours_passed > 0:
                updated += 1
            # после decay флаг в row устарел — перечитаем для warning_sent
            fresh = db.get_upkeep_by_id(int(row["id"]))
            if fresh is None:
                continue
            await _check_upkeep_alerts(bot, fresh, silver, left, channel)
        if updated > 0:
            system_logger.debug(
                f"Upkeep maintenance completed for {updated} objects"
            )
        await refresh_upkeep_panel(bot)
    except Exception as exc:
        error_msg = f"Ошибка в maintain_upkeep: {exc}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")


def start_upkeep_tasks(bot: BeaconBot) -> None:
    if not maintain_upkeep.is_running():
        maintain_upkeep.start(bot)
