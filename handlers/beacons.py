"""Slash-команды управления маяками."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

import config
from services import database as db
from services.beacon_service import get_beacon_panel_thread, refresh_beacon_panel
from utils.formatting import get_user_info, rate_from_priority
from utils.logging_setup import action_logger, error_logger

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    beacon = app_commands.Group(
        name="beacon",
        description="Управление маяками",
    )

    @beacon.command(name="add", description="Добавить новый маяк")
    @app_commands.describe(
        beacon_id="ID маяка (например: NG-01)",
        priority="Тип маяка (Фронтовой / Тыловой)",
        fuel="Количество топлива (0-30, оставьте пустым для полного бака)",
        lifetime="Прочность в процентах (0-100, оставьте пустым для полной прочности)",
        image="Изображение маяка (обязательно! Перетащите или нажмите для загрузки)",
    )
    @app_commands.choices(
        priority=[
            app_commands.Choice(
                name="Фронтовой (быстрый расход топлива)",
                value=config.BEACON_TYPE_FRONT,
            ),
            app_commands.Choice(
                name="Тыловой (обычный)",
                value=config.BEACON_TYPE_REAR,
            ),
        ]
    )
    async def add(
        interaction: discord.Interaction,
        beacon_id: str,
        priority: app_commands.Choice[int],
        image: discord.Attachment,
        fuel: Optional[str] = None,
        lifetime: Optional[str] = None,
    ) -> None:
        if not beacon_id or len(beacon_id) > 20:
            await interaction.response.send_message(
                "❌ ID маяка должен быть от 1 до 20 символов!",
                ephemeral=True,
            )
            return

        if not image.content_type or not image.content_type.startswith("image/"):
            await interaction.response.send_message(
                "❌ Загруженный файл должен быть изображением!",
                ephemeral=True,
            )
            return

        if image.size > 25 * 1024 * 1024:
            await interaction.response.send_message(
                "❌ Размер изображения не должен превышать 25MB!",
                ephemeral=True,
            )
            return

        try:
            if fuel and fuel.strip():
                current_fuel = float(fuel)
                if current_fuel < 0 or current_fuel > config.MAX_FUEL:
                    await interaction.response.send_message(
                        f"❌ Топливо должно быть от 0 до {config.MAX_FUEL}!",
                        ephemeral=True,
                    )
                    return
            else:
                current_fuel = config.MAX_FUEL
        except ValueError:
            await interaction.response.send_message(
                "❌ Топливо должно быть числом!",
                ephemeral=True,
            )
            return

        try:
            if lifetime and lifetime.strip():
                current_lifetime = float(lifetime)
                if current_lifetime < 0 or current_lifetime > config.MAX_LIFETIME:
                    await interaction.response.send_message(
                        f"❌ Прочность должна быть от 0 до {config.MAX_LIFETIME}!",
                        ephemeral=True,
                    )
                    return
            else:
                current_lifetime = config.MAX_LIFETIME
        except ValueError:
            await interaction.response.send_message(
                "❌ Прочность должна быть числом!",
                ephemeral=True,
            )
            return

        user_info = get_user_info(interaction)

        if db.beacon_exists(beacon_id):
            action_logger.warning(
                f"{user_info} tried to add duplicate beacon {beacon_id}"
            )
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} уже существует!",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        username = interaction.user.name
        rate = rate_from_priority(priority.value)

        try:
            await interaction.response.defer(ephemeral=True)

            bot = interaction.client
            thread = await get_beacon_panel_thread(bot)  # type: ignore[arg-type]
            if thread is None:
                await interaction.followup.send(
                    "❌ Панель маяков недоступна "
                    "(проверьте PANEL_CHANNEL_ID и права бота на ветки).",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title=beacon_id,
                color=discord.Color.green(),
            )

            filename = image.filename or "beacon.png"
            file = await image.to_file(filename=filename)
            embed.set_image(url=f"attachment://{filename}")

            try:
                sent_message = await thread.send(
                    content=f"Добавил: {interaction.user.display_name}",
                    embed=embed,
                    file=file,
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ Боту не хватает прав во ветке панели маяков.\n"
                    "Нужны: **Просмотр канала**, **Писать в ветках**, "
                    "**Прикреплять файлы**, **Встраивать ссылки**, "
                    "**Создавать публичные ветки**, **Управлять ветками**.",
                    ephemeral=True,
                )
                return

            db.insert_beacon(
                beacon_id=beacon_id,
                current_fuel=current_fuel,
                current_lifetime=current_lifetime,
                fuel_consumption_rate=rate,
                message_link=sent_message.jump_url,
                username=username,
                created_by=user_id,
            )
            db.increment_user_stat(user_id, username, "created")
            await refresh_beacon_panel(bot)  # type: ignore[arg-type]

            action_logger.info(
                f"{user_info} added beacon {beacon_id} | "
                f"Fuel: {current_fuel}/{config.MAX_FUEL}, "
                f"Lifetime: {current_lifetime}%, Priority: {priority.value} | "
                f"thread={thread.id} message={sent_message.id}"
            )

            await interaction.followup.send(
                f"✅ Маяк {beacon_id} добавлен. "
                f"Изображение локации — в ветке панели.",
                ephemeral=True,
            )

        except sqlite3.IntegrityError:
            action_logger.warning(
                f"{user_info} duplicate beacon {beacon_id} (integrity constraint)"
            )
            send = (
                interaction.followup.send
                if interaction.response.is_done()
                else interaction.response.send_message
            )
            await send(
                f"❌ Маяк {beacon_id} уже существует!",
                ephemeral=True,
            )
        except discord.Forbidden as exc:
            error_logger.error(
                f"{user_info} Forbidden при создании маяка: {exc}",
                exc_info=True,
            )
            send = (
                interaction.followup.send
                if interaction.response.is_done()
                else interaction.response.send_message
            )
            await send(
                "❌ Боту не хватает прав в канале/ветке панели маяков.\n"
                "Нужны: **Просмотр канала**, **Писать в ветках**, "
                "**Прикреплять файлы**, **Встраивать ссылки**, "
                "**Создавать публичные ветки**, **Управлять ветками**.",
                ephemeral=True,
            )
        except Exception as exc:
            error_logger.error(
                f"{user_info} Ошибка при создании маяка: {exc}",
                exc_info=True,
            )
            send = (
                interaction.followup.send
                if interaction.response.is_done()
                else interaction.response.send_message
            )
            await send(f"❌ Ошибка: {exc}", ephemeral=True)

    bot.tree.add_command(beacon)

    @bot.tree.command(name="ping", description="Проверка, что бот жив")
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🏓 Pong!", ephemeral=True)
