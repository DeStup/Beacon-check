"""Бизнес-логика кормёжки: сытость лошадей и ослов."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import tasks

import config
from services import database as db
from services.beacon_service import hours_since
from utils.embeds import progress_bar
from utils.logging_setup import error_logger, feed_logger, system_logger

if TYPE_CHECKING:
    from bot import BeaconBot

_panel_lock = asyncio.Lock()


def normalize_animal_type(raw: str) -> str:
    key = raw.strip().lower()
    if key not in config.FEED_ANIMAL_HOURS_TO_EMPTY:
        raise ValueError(f"Неизвестный тип животного: {raw}")
    return key


def animal_emoji(animal_type: str) -> str:
    return config.FEED_ANIMAL_EMOJIS.get(animal_type, "🐾")


def animal_label(animal_type: str) -> str:
    return config.FEED_ANIMAL_LABELS.get(animal_type, animal_type)


def animal_display(animal_type: str, name: str) -> str:
    return f"{animal_emoji(animal_type)} **{name}**"


def satiety_decay_per_hour(animal_type: str) -> float:
    hours = config.FEED_ANIMAL_HOURS_TO_EMPTY[normalize_animal_type(animal_type)]
    if hours <= 0:
        return 0.0
    return config.FEED_MAX_SATIETY / hours


def compute_current_satiety(
    satiety: float,
    animal_type: str,
    last_updated: str,
) -> float:
    hours_passed = hours_since(last_updated)
    if hours_passed <= 0:
        return max(0.0, min(config.FEED_MAX_SATIETY, satiety))
    rate = satiety_decay_per_hour(animal_type)
    return max(0.0, satiety - rate * hours_passed)


def snapshot_feed(row: Any) -> dict[str, Any]:
    animal_type = normalize_animal_type(str(row["animal_type"]))
    current = compute_current_satiety(
        float(row["satiety"]),
        animal_type,
        row["last_updated"],
    )
    try:
        low_warned = bool(row["low_warning_sent"])
    except (KeyError, IndexError):
        low_warned = False
    try:
        death_notified = bool(row["death_notified"])
    except (KeyError, IndexError):
        death_notified = False
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "animal_type": animal_type,
        "satiety": current,
        "is_dead": current <= 0,
        "low_warning_sent": low_warned,
        "death_notified": death_notified,
    }


def apply_decay_to_feed(row: Any) -> float:
    animal_type = normalize_animal_type(str(row["animal_type"]))
    current = compute_current_satiety(
        float(row["satiety"]),
        animal_type,
        row["last_updated"],
    )
    if hours_since(row["last_updated"]) > 0:
        db.apply_feed_decay_update(
            int(row["id"]),
            current,
            datetime.now().isoformat(),
        )
    return current


def apply_decay_to_all_feed() -> int:
    updated = 0
    for row in db.fetch_all_feed_for_update():
        if hours_since(row["last_updated"]) > 0:
            apply_decay_to_feed(row)
            updated += 1
    return updated


def format_feed_status_table(snaps: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for snap in snaps:
        emoji = animal_emoji(snap["animal_type"])
        satiety = snap["satiety"]
        bar = progress_bar(
            satiety,
            config.FEED_MAX_SATIETY,
            filled_char="▓",
            empty_char="░",
        )
        if snap["is_dead"]:
            status = "💀"
            pct_text = "0%"
        elif satiety < config.FEED_WARNING_THRESHOLD:
            status = "⚠️"
            pct = int(satiety) if satiety == int(satiety) else round(satiety, 1)
            pct_text = f"{pct}%"
        else:
            status = "☑️"
            pct = int(satiety) if satiety == int(satiety) else round(satiety, 1)
            pct_text = f"{pct}%"
        lines.append(
            f"{emoji} **{snap['name']}**\n"
            f"{status} {bar} `{pct_text}`"
        )
    return "\n".join(lines)


def build_all_feed_status_embed() -> discord.Embed:
    rows = db.list_all_feed()
    if not rows:
        return discord.Embed(
            title="Панель Сытости Животных",
            description="📭 Нет животных на мониторинге",
            color=discord.Color.dark_grey(),
            timestamp=datetime.now(),
        )

    snaps = [snapshot_feed(row) for row in rows[:25]]
    has_warning = any(
        snap["is_dead"] or snap["satiety"] < config.FEED_WARNING_THRESHOLD
        for snap in snaps
    )
    color = (
        discord.Color.yellow()
        if has_warning
        else discord.Color.green()
    )
    embed = discord.Embed(
        title="Панель Сытости Животных",
        description=format_feed_status_table(snaps),
        color=color,
        timestamp=datetime.now(),
    )
    if len(rows) > 25:
        embed.set_footer(text=f"Показаны первые 25 из {len(rows)}")
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


async def refresh_feed_panel(
    bot: BeaconBot,
    *,
    edit_existing: bool = True,
) -> discord.Message | None:
    async with _panel_lock:
        return await _refresh_feed_panel_locked(
            bot, edit_existing=edit_existing
        )


async def _refresh_feed_panel_locked(
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
                f"Канал панели кормёжки недоступен: {exc}",
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

    from handlers.views.feed_views import FeedMenuView

    embed = build_all_feed_status_embed()
    view = FeedMenuView()
    saved = db.get_feed_panel()

    if saved is not None:
        saved_channel_id, message_id = saved
        if saved_channel_id == config.PANEL_CHANNEL_ID:
            try:
                message = await channel.fetch_message(message_id)
                if not edit_existing:
                    return message
                await message.edit(embed=embed, view=view)
                return message
            except Exception as exc:
                from services.panel_service import is_unknown_message

                if is_unknown_message(exc):
                    db.clear_feed_panel()
                    system_logger.info(
                        "Feed panel message missing — will recreate"
                    )
                else:
                    error_logger.error(
                        f"Не удалось обновить панель кормёжки: {exc}",
                        exc_info=True,
                    )
                    return None
        else:
            db.clear_feed_panel()

    try:
        message = await channel.send(embed=embed, view=view)
        db.set_feed_panel(config.PANEL_CHANNEL_ID, message.id)
        system_logger.info(
            f"Feed panel created in channel "
            f"{config.PANEL_CHANNEL_ID} message={message.id}"
        )
        return message
    except discord.HTTPException as exc:
        error_logger.error(
            f"Не удалось создать панель кормёжки: {exc}",
            exc_info=True,
        )
        return None


async def ensure_feed_panel(bot: BeaconBot) -> None:
    from handlers.views.feed_views import FeedMenuView

    if not getattr(bot, "_feed_panel_view_registered", False):
        bot.add_view(FeedMenuView())
        setattr(bot, "_feed_panel_view_registered", True)
    if not config.PANEL_CHANNEL_ID:
        system_logger.warning(
            "PANEL_CHANNEL_ID не задан — панель кормёжки отключена"
        )
        return
    await refresh_feed_panel(bot)


def _alert_channel(bot: BeaconBot) -> discord.abc.Messageable | None:
    if not config.ALERT_CHANNEL_ID:
        return None
    return bot.get_channel(config.ALERT_CHANNEL_ID)


async def _check_feed_alerts(
    bot: BeaconBot,
    row: Any,
    satiety: float,
    channel: discord.abc.Messageable | None,
) -> None:
    animal_id = int(row["id"])
    name = row["name"]
    animal_type = normalize_animal_type(str(row["animal_type"]))
    display = animal_display(animal_type, name)
    try:
        low_warned = bool(row["low_warning_sent"])
    except (KeyError, IndexError):
        low_warned = False
    try:
        death_notified = bool(row["death_notified"])
    except (KeyError, IndexError):
        death_notified = False

    if satiety <= 0:
        if not death_notified:
            if channel:
                verb = "умерла" if animal_type == "horse" else "умер"
                await channel.send(
                    f"> 💀 {display} {verb} от голода."
                )
            db.set_feed_death_notified(animal_id, True)
            db.set_feed_low_warning(animal_id, True)
            feed_logger.info(f"Feed death notified for {name}")
        return

    if satiety < config.FEED_WARNING_THRESHOLD:
        if not low_warned:
            if channel:
                pct = int(round(satiety))
                await channel.send(
                    f"> ⚠️ Мало сытости у {display} — `{pct}%`"
                )
            db.set_feed_low_warning(animal_id, True)
            feed_logger.info(
                f"Feed low warning for {name} (satiety={satiety:.1f})"
            )
    elif low_warned and satiety >= config.FEED_WARNING_THRESHOLD:
        db.set_feed_low_warning(animal_id, False)
        if death_notified:
            db.set_feed_death_notified(animal_id, False)


@tasks.loop(minutes=1)
async def maintain_feed(bot: BeaconBot) -> None:
    try:
        rows = db.fetch_all_feed_for_update()
        channel = _alert_channel(bot)
        for row in rows:
            apply_decay_to_feed(row)
            fresh = db.get_feed_by_id(int(row["id"]))
            if fresh is None:
                continue
            satiety = float(fresh["satiety"])
            await _check_feed_alerts(bot, fresh, satiety, channel)
        await refresh_feed_panel(bot)
    except Exception as exc:
        error_msg = f"Ошибка в maintain_feed: {exc}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")


@maintain_feed.before_loop
async def _before_maintain_feed() -> None:
    await asyncio.sleep(config.FEED_MAINTAIN_OFFSET_SEC)


def start_feed_tasks(bot: BeaconBot) -> None:
    if not maintain_feed.is_running():
        maintain_feed.start(bot)
