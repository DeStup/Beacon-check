"""Slash-команды управления маяками."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

import config
from handlers.views.clear import ConfirmClearView
from handlers.views.menu import BeaconMenuView, open_beacon_select
from services import database as db
from utils.formatting import format_priority, get_user_info, rate_from_priority
from utils.logging_setup import action_logger, error_logger
from utils.permissions import can_clear_beacons

if TYPE_CHECKING:
    from bot import BeaconBot


def setup(bot: BeaconBot) -> None:
    @bot.tree.command(name="add", description="Добавить новый маяк")
    @app_commands.describe(
        beacon_id="ID маяка (например: NG-01)",
        priority="Приоритет маяка (1 - высокий, 2 - средний, 3 - низкий)",
        fuel="Количество топлива (0-30, оставьте пустым для полного бака)",
        lifetime="Прочность в процентах (0-100, оставьте пустым для полной прочности)",
        image="Изображение маяка (обязательно! Перетащите или нажмите для загрузки)",
    )
    @app_commands.choices(
        priority=[
            app_commands.Choice(
                name="🔴 1 - Высокий (быстрый расход топлива)",
                value=1,
            ),
            app_commands.Choice(
                name="🟡 2 - Средний (стандартный расход)",
                value=2,
            ),
            app_commands.Choice(
                name="🟢 3 - Низкий (экономный расход)",
                value=3,
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

        if db.beacon_exists(beacon_id):
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} уже существует!",
                ephemeral=True,
            )
            return

        user_info = get_user_info(interaction)
        user_id = str(interaction.user.id)
        username = interaction.user.name
        rate = rate_from_priority(priority.value)
        priority_text = format_priority(rate)

        try:
            embed = discord.Embed(
                title="✅ Добавлен маяк",
                description=f"**{beacon_id}**",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="🔋 Топливо",
                value=f"{current_fuel:.1f}/{config.MAX_FUEL}",
            )
            embed.add_field(
                name="🔄 Прочность",
                value=f"{current_lifetime:.1f}%",
            )
            embed.add_field(name="📊 Приоритет", value=priority_text)
            embed.add_field(
                name="",
                value=f"Добавил: {interaction.user.mention}",
                inline=False,
            )
            embed.set_image(url=image.url)

            if not interaction.channel:
                await interaction.response.send_message(
                    "❌ Не удалось определить канал!",
                    ephemeral=True,
                )
                return

            sent_message = await interaction.channel.send(embed=embed)
            db.insert_beacon(
                beacon_id=beacon_id,
                current_fuel=current_fuel,
                current_lifetime=current_lifetime,
                fuel_consumption_rate=rate,
                message_link=sent_message.jump_url,
                username=username,
            )
            db.increment_user_stat(user_id, username, "created")

            action_logger.info(
                f"{user_info} added beacon {beacon_id} | "
                f"Fuel: {current_fuel}/{config.MAX_FUEL}, "
                f"Lifetime: {current_lifetime}%, Priority: {priority.value}"
            )

            await interaction.response.send_message(
                f"✅ Маяк {beacon_id} успешно добавлен с изображением!",
                ephemeral=True,
            )

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} уже существует!",
                ephemeral=True,
            )
        except Exception as exc:
            error_logger.error(
                f"{user_info} Ошибка при создании маяка: {exc}",
                exc_info=True,
            )
            await interaction.response.send_message(
                f"❌ Ошибка: {exc}",
                ephemeral=True,
            )

    @bot.tree.command(name="menu", description="Показать меню управления маяками")
    async def menu(interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🚀 Управление маяками",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Доступные действия:",
            value=(
                "**➕ Добавить маяк** - добавить новый маяк\n"
                "**⛽ Заправить** - пополнить топливо маяка\n"
                "**📊 Статус** - показать статус всех маяков\n"
                "**✏️ Редактировать** - изменить данные маяка\n"
                "**🗑️ Удалить** - удалить маяк\n"
                "**🔄 Обновить** - обновить данные\n"
                "**🧹 Очистить всё** - удалить все маяки (админ)"
            ),
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=BeaconMenuView(),
            ephemeral=True,
        )

    @bot.tree.command(name="refuel", description="Пополнить топливо маяка")
    async def refuel(interaction: discord.Interaction) -> None:
        await open_beacon_select(
            interaction,
            action="refuel",
            title="⛽ Заправка маяка",
            description="Выберите маяк из списка ниже:",
            empty_message="❌ Нет активных маяков для заправки!",
        )

    @bot.tree.command(name="status", description="Показать статус маяка")
    async def status(interaction: discord.Interaction) -> None:
        await open_beacon_select(
            interaction,
            action="status",
            title="📊 Просмотр статуса маяка",
            description=(
                "Выберите маяк для просмотра детального статуса\n"
                "или выберите 'Показать все маяки' для общего обзора"
            ),
            empty_message="📭 Нет активных маяков",
        )

    @bot.tree.command(name="edit", description="Редактировать данные маяка")
    async def edit(interaction: discord.Interaction) -> None:
        await open_beacon_select(
            interaction,
            action="edit",
            title="✏️ Редактирование маяка",
            description="Выберите маяк из списка ниже:",
            empty_message="❌ Нет активных маяков для редактирования!",
        )

    @bot.tree.command(name="delete", description="Удалить маяк")
    async def delete(interaction: discord.Interaction) -> None:
        await open_beacon_select(
            interaction,
            action="delete",
            title="🗑️ Удаление маяка",
            description="Выберите маяк из списка ниже:",
            empty_message="❌ Нет активных маяков для удаления!",
            color=discord.Color.red(),
        )

    @bot.tree.command(name="clear", description="Удалить все маяки")
    async def clear(interaction: discord.Interaction) -> None:
        if not can_clear_beacons(interaction.user):
            embed = discord.Embed(
                title="❌ Доступ запрещен",
                description="У вас нет прав для выполнения этой команды!",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="⚠️ Подтверждение действия",
            description=(
                "Вы уверены, что хотите удалить **ВСЕ** маяки?\n"
                "Это действие нельзя отменить!"
            ),
            color=discord.Color.yellow(),
        )
        embed.set_footer(text="У вас есть 30 секунд на подтверждение")
        view = ConfirmClearView(
            interaction.user,
            interaction,
            yes_label="Да",
            no_label="Нет",
        )
        # Для /clear стиль кнопок как в оригинале: зелёная Да / красная Нет
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "Да":
                    child.style = discord.ButtonStyle.green
                elif child.label == "Нет":
                    child.style = discord.ButtonStyle.red

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @bot.tree.command(name="ping", description="Проверка, что бот жив")
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🏓 Pong!", ephemeral=True)
