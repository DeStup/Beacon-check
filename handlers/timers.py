"""Slash-команды пользовательских таймеров."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ui import Select, View

import config
from services import database as db
from utils.formatting import get_user_info
from utils.logging_setup import timer_logger
from utils.permissions import can_cancel_timer

if TYPE_CHECKING:
    from bot import BeaconBot


def _duration_seconds(d: int, h: int, m: int) -> int:
    return d * 86_400 + h * 3_600 + m * 60


def _format_duration(total: int) -> str:
    days, rem = divmod(total, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes or not parts:
        parts.append(f"{minutes} мин")
    return " ".join(parts)


def _build_status_embed(rows: list[db.Row]) -> discord.Embed:
    embed = discord.Embed(
        title="⏱️ Активные таймеры",
        color=discord.Color.blurple(),
        timestamp=datetime.now(),
    )
    if not rows:
        embed.description = "Нет активных таймеров."
        return embed

    shown = rows[:25]
    for row in shown:
        trigger_at = datetime.fromisoformat(row["trigger_at"])
        unix_ts = int(trigger_at.timestamp())
        embed.add_field(
            name=row["name"],
            value=(
                f"Сработка: <t:{unix_ts}:f> (<t:{unix_ts}:R>)\n"
                f"Создал: {row['created_by_name']}"
            ),
            inline=False,
        )
    footer = f"Всего: {len(rows)}"
    if len(rows) > 25:
        footer += " (показаны первые 25)"
    embed.set_footer(text=footer)
    return embed


class TimerCancelSelect(Select):
    def __init__(
        self,
        bot: BeaconBot,
        rows: list[db.Row],
        requester_id: int,
    ) -> None:
        options: list[discord.SelectOption] = []
        for row in rows[:25]:
            label = str(row["name"])
            if len(label) > 100:
                label = label[:97] + "..."
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(row["id"]),
                    description=f"Создал: {row['created_by_name']}"[:100],
                )
            )
        super().__init__(
            placeholder="Выберите таймер для отмены…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.bot = bot
        self.requester_id = requester_id
        self._rows_by_id = {int(r["id"]): r for r in rows}

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Вы не можете управлять этим меню!",
                ephemeral=True,
            )
            return

        timer_id = int(self.values[0])
        row = self._rows_by_id.get(timer_id) or db.get_timer(timer_id)
        if row is None or row["status"] != "active":
            await interaction.response.send_message(
                "❌ Таймер не найден или уже завершён.",
                ephemeral=True,
            )
            return

        if not can_cancel_timer(interaction.user, int(row["created_by_id"])):
            await interaction.response.send_message(
                "❌ Отменить может только создатель или модератор.",
                ephemeral=True,
            )
            return

        user_info = get_user_info(interaction)
        cancelled = await self.bot.timer_manager.cancel(
            timer_id,
            user_info=user_info,
        )
        if cancelled:
            await interaction.response.send_message(
                f"✅ Таймер **{row['name']}** отменён.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ Таймер не найден или уже завершён.",
                ephemeral=True,
            )


class TimerStatusView(View):
    def __init__(
        self,
        bot: BeaconBot,
        rows: list[db.Row],
        requester: discord.abc.User,
    ) -> None:
        super().__init__(timeout=120)
        cancellable = [
            r
            for r in rows
            if can_cancel_timer(requester, int(r["created_by_id"]))
        ]
        if cancellable:
            self.add_item(TimerCancelSelect(bot, cancellable, requester.id))


def setup(bot: BeaconBot) -> None:
    timer = app_commands.Group(
        name="timer",
        description="Пользовательские таймеры",
    )

    @timer.command(
        name="add",
        description=(
            "Создать таймер (day/hour/minute; пропуск = 0, максимум 7 дней)"
        ),
    )
    @app_commands.describe(
        name="Имя таймера (до 50 символов)",
        warn="Когда уведомить (0 = в момент окончания)",
        day="Дни (по умолчанию 0)",
        hour="Часы (по умолчанию 0)",
        minute="Минуты (по умолчанию 0)",
    )
    @app_commands.choices(
        warn=[
            app_commands.Choice(name="В момент окончания", value=0),
            app_commands.Choice(name="За 5 минут", value=5),
            app_commands.Choice(name="За 10 минут", value=10),
            app_commands.Choice(name="За 15 минут", value=15),
            app_commands.Choice(name="За 20 минут", value=20),
            app_commands.Choice(name="За 30 минут", value=30),
            app_commands.Choice(name="За 1 час", value=60),
            app_commands.Choice(name="За 2 часа", value=120),
            app_commands.Choice(name="За 3 часа", value=180),
        ]
    )
    async def add(
        interaction: discord.Interaction,
        name: str,
        warn: app_commands.Choice[int],
        day: Optional[int] = None,
        hour: Optional[int] = None,
        minute: Optional[int] = None,
    ) -> None:
        user_info = get_user_info(interaction)
        name = name.strip()
        if not name:
            await interaction.response.send_message(
                "❌ Имя таймера обязательно!",
                ephemeral=True,
            )
            return
        if len(name) > config.MAX_TIMER_NAME_LENGTH:
            await interaction.response.send_message(
                f"❌ Имя не должно превышать {config.MAX_TIMER_NAME_LENGTH} символов!",
                ephemeral=True,
            )
            return

        warning_minutes = int(warn.value)
        days = day if day is not None else 0
        hours = hour if hour is not None else 0
        minutes = minute if minute is not None else 0

        for label, value in (
            ("дни", days),
            ("часы", hours),
            ("минуты", minutes),
        ):
            if value < 0:
                await interaction.response.send_message(
                    f"❌ {label.capitalize()} не могут быть отрицательными!",
                    ephemeral=True,
                )
                return

        total = _duration_seconds(days, hours, minutes)
        if total <= 0:
            await interaction.response.send_message(
                "❌ Укажите длительность больше нуля (day/hour/minute)!",
                ephemeral=True,
            )
            return
        if total > config.MAX_TIMER_SECONDS:
            await interaction.response.send_message(
                "❌ Таймер не должен превышать 7 дней!",
                ephemeral=True,
            )
            return
        if warning_minutes > 0 and total <= warning_minutes * 60:
            await interaction.response.send_message(
                "❌ Длительность таймера должна быть больше времени уведомления!",
                ephemeral=True,
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message(
                "❌ Команду можно использовать только в канале.",
                ephemeral=True,
            )
            return

        _, trigger_at = await bot.timer_manager.add_timer(
            bot,
            name=name,
            duration_seconds=total,
            warning_minutes=warning_minutes,
            created_by_id=interaction.user.id,
            created_by_name=interaction.user.name,
            channel_id=interaction.channel.id,
            guild_id=interaction.guild_id,
            user_info=user_info,
        )

        unix_ts = int(trigger_at.timestamp())
        embed = discord.Embed(
            title="✅ Таймер создан",
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Имя", value=name, inline=False)
        embed.add_field(
            name="Длительность",
            value=_format_duration(total),
            inline=True,
        )
        embed.add_field(
            name="Уведомление",
            value=warn.name,
            inline=True,
        )
        embed.add_field(
            name="Время",
            value=f"<t:{unix_ts}:f> (<t:{unix_ts}:R>)",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @timer.command(
        name="status",
        description="Показать все активные таймеры",
    )
    async def status(interaction: discord.Interaction) -> None:
        user_info = get_user_info(interaction)
        rows = db.list_active_timers()
        timer_logger.info(
            f"{user_info} checked timer status (count={len(rows)})"
        )
        embed = _build_status_embed(rows)
        kwargs: dict = {"embed": embed, "ephemeral": True}
        if rows:
            view = TimerStatusView(bot, rows, interaction.user)
            if view.children:
                kwargs["view"] = view
        await interaction.response.send_message(**kwargs)

    bot.tree.add_command(timer)
