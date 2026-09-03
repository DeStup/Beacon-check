"""Бизнес-логика upkeep: расход серебра и предупреждения."""

from __future__ import annotations

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
    text = format_duration_hours(hours_left)
    if hours_left > 0 and hours_left != float("inf"):
        deplete_at = datetime.now() + timedelta(hours=hours_left)
        unix = int(deplete_at.timestamp())
        return f"{text} (<t:{unix}:R>)"
    return text


def format_upkeep_status_table(snaps: list[dict[str, Any]]) -> str:
    """Моноширинная таблица для embed (выравнивание столбцов)."""
    name_w, rate_w, stock_w, left_w = 16, 10, 10, 12
    header = (
        f"{'Объект':<{name_w}} "
        f"{'Содерж./ч':>{rate_w}} "
        f"{'Склад':>{stock_w}} "
        f"{'Хватит':>{left_w}}"
    )
    sep = (
        f"{'─' * name_w} "
        f"{'─' * rate_w} "
        f"{'─' * stock_w} "
        f"{'─' * left_w}"
    )
    lines = [header, sep]
    for snap in snaps:
        name = str(snap["name"])
        if len(name) > name_w:
            name = name[: name_w - 1] + "…"
        mark = "!" if snap["hours_left"] < config.UPKEEP_WARNING_HOURS else " "
        if snap["hours_left"] == float("inf"):
            left = "∞"
        else:
            left = format_duration_hours(snap["hours_left"])
        if len(left) > left_w:
            left = left[:left_w]
        lines.append(
            f"{mark}{name:<{name_w - 1}} "
            f"{display_silver_rate(snap['silver_per_hour']):>{rate_w}d} "
            f"{display_silver_amount(snap['silver_amount']):>{stock_w}d} "
            f"{left:>{left_w}}"
        )
    return "```\n" + "\n".join(lines) + "\n```"


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
        name="<:silver:1545181851423866890> Содержание",
        value=f"{display_silver_rate(silver_per_hour)} серебра/час",
        inline=True,
    )
    embed.add_field(
        name="<:keystone:1545182139862229002> Склад",
        value=f"{display_silver_amount(silver_amount)} серебра",
        inline=True,
    )
    left_name = "⏳ Хватит на"
    if 0 < hours_left < config.UPKEEP_WARNING_HOURS:
        left_name = "⚠️ Хватит на"
    elif hours_left <= 0:
        left_name = "💀 Хватит на"
    embed.add_field(
        name=left_name,
        value=format_hours_left_display(hours_left),
        inline=False,
    )
    return embed


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
            left_text = format_hours_left_display(hours_left)
            if hours_left <= 0:
                await channel.send(
                    f"💀 Серебро закончилось! **{name}** — "
                    f"содержание {display_silver_rate(rate)}/ч, "
                    f"склад {display_silver_amount(silver)}"
                )
            else:
                await channel.send(
                    f"⚠️ Мало серебра на содержание! **{name}** — "
                    f"содержание {display_silver_rate(rate)}/ч, "
                    f"склад {display_silver_amount(silver)}, "
                    f"хватит на {left_text}"
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
    except Exception as exc:
        error_msg = f"Ошибка в maintain_upkeep: {exc}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")


def start_upkeep_tasks(bot: BeaconBot) -> None:
    if not maintain_upkeep.is_running():
        maintain_upkeep.start(bot)
