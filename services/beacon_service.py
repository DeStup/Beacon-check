"""Бизнес-логика маяков: расход топлива, проверки, алерты."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import tasks

import config
from services import database as db
from utils.embeds import progress_bar, status_emoji
from utils.logging_setup import action_logger, error_logger

if TYPE_CHECKING:
    from bot import BeaconBot


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
            f"🔋 {progress_bar(fuel, config.MAX_FUEL)} "
            f"{fuel:.1f}/{config.MAX_FUEL} ({fuel_percent:.1f}%)"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"{status_emoji(lifetime)} Прочность",
        value=f"🔄 {progress_bar(lifetime, config.MAX_LIFETIME)} {lifetime:.1f}%",
        inline=False,
    )
    if message_link:
        embed.add_field(name="", value=f"🔗 [Перейти]({message_link})", inline=False)
    return embed


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
        action_logger.debug(
            f"Auto-update beacon {beacon['beacon_id']}: "
            f"Hours passed: {hours_passed:.2f}, "
            f"Fuel: {current_fuel:.1f}→{new_fuel:.1f}, "
            f"Lifetime: {current_lifetime:.1f}→{new_lifetime:.1f}"
        )

    if new_fuel <= 0 or current_fuel <= 0:
        action_logger.debug(
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
            await channel.send(f"🗑️ Маяк {beacon_id} удалён: {reason}")
        action_logger.info(f"Auto-deleted beacon {beacon_id}: {reason}")
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
        action_logger.info(f"Beacon {beacon_id} recovered to normal status")


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
            action_logger.debug(
                f"Beacon maintenance completed for {updated_count} beacons"
            )
    except Exception as exc:
        error_msg = f"Ошибка в maintain_beacons: {exc}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")
        # Не re-raise: цикл должен продолжать работать после сбоя


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
