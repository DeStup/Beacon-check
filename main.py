import os
import sqlite3
from datetime import datetime
from typing import List, Optional

import discord
from discord.ui import Button, View, Modal, TextInput, Select
from discord.ext import tasks
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
# Константы
MAX_FUEL = 30  # Максимальное значение топлива (единицы)
MAX_LIFETIME = 100  # Максимальный срок действия (проценты)
FUEL_HIGH_CONSUMPTION_RATE = 1 / 1  # 1 единица топлива расходуется за 1 часа при обнаружении противника или вражеских строений
FUEL_MEDIUM_CONSUMPTION_RATE = 1 / 1.5  # Ориентировочный расход топлива за 1 час, при редком обнаружении
FUEL_LOW_CONSUMPTION_RATE = 1 / 1.9  # 1 единица топлива расходуется за 1 часа если маяк в тылу
LIFETIME_DECAY_RATE = 100 / 48  # 100% расходуется за 48 часа (в процентах в час)

intents = discord.Intents.default()
intents.message_content = True


class SlashClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        guild = discord.Object(id=os.getenv("GUILD"))
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


bot = SlashClient()


# TODO вынести логику бд отдельно
def get_db_connection():
    conn = sqlite3.connect('./data/beacons.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS beacons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            beacon_id TEXT NOT NULL UNIQUE,
            current_fuel INTEGER NOT NULL,
            current_lifetime INTEGER NOT NULL,
            fuel_consumption_rate INTEGER NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            low_status_sent BOOLEAN DEFAULT FALSE
        )
    ''')
    conn.commit()
    conn.close()


init_db()


@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    update_beacons.start()
    check_beacons.start()


def calculate_decay(last_updated):
    now = datetime.now()
    last_update = datetime.fromisoformat(last_updated)
    hours_passed = (now - last_update).total_seconds() / 3600
    return hours_passed


@tasks.loop(minutes=1)
async def update_beacons():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM beacons')
    beacons = cursor.fetchall()

    now = datetime.now().isoformat()

    for beacon in beacons:
        hours_passed = calculate_decay(beacon['last_updated'])

        if hours_passed <= 0:
            continue

        new_fuel = float(beacon['current_fuel']) - float(1 / beacon['fuel_consumption_rate'] * hours_passed)
        new_lifetime = float(beacon['current_lifetime']) - (LIFETIME_DECAY_RATE * hours_passed)

        # Гарантируем, что значения не уйдут ниже 0
        new_fuel = max(0, new_fuel)
        new_lifetime = max(0, new_lifetime)

        cursor.execute('''
            UPDATE beacons 
            SET current_fuel = ?, current_lifetime = ?, last_updated = ?
            WHERE id = ?
        ''', (new_fuel, new_lifetime, now, beacon['id']))

    conn.commit()
    conn.close()


@tasks.loop(minutes=1)
async def check_beacons():
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Получаем все маяки из базы данных
        cursor.execute('SELECT * FROM beacons')
        beacons = cursor.fetchall()

        for beacon in beacons:
            beacon_id = beacon['beacon_id']
            current_fuel = float(beacon['current_fuel'])
            current_lifetime = float(beacon['current_lifetime'])

            # Безопасное получение статуса уведомления
            try:
                low_status_sent = bool(beacon['low_status_sent'])
            except (KeyError, IndexError):
                low_status_sent = False  # Значение по умолчанию если колонки нет

            now = datetime.now().isoformat()

            # 1. Проверка на полностью сгнившие маяки (lifetime <= 0)
            if current_lifetime <= 0:
                channel = bot.get_channel(int(os.getenv("ALERT_ROLE_ID")))
                await channel.send(
                    f"🗑️ Маяк {beacon_id} полностью сгнил и был автоматически удалён"
                )
                cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
                conn.commit()
                continue

            # 2. Проверка низких показателей
            fuel_percent = (current_fuel / MAX_FUEL) * 100
            lifetime_percent = current_lifetime

            if (fuel_percent < 20 or lifetime_percent < 20) and not low_status_sent:
                channel = bot.get_channel(int(os.getenv("ALERT_ROLE_ID")))
                status_msgs = []

                if fuel_percent < 20:
                    status_msgs.append(f"топливо: {current_fuel:.1f} ({fuel_percent:.1f}%)")
                if lifetime_percent < 20:
                    status_msgs.append(f"срок: {lifetime_percent:.1f}%")

                await channel.send(
                    f"⚠️ Внимание! Маяк {beacon_id} имеет низкие показатели:\n"
                    f"- {'; '.join(status_msgs)}"
                )

                # Обновляем статус уведомления
                cursor.execute('''
                    UPDATE beacons 
                    SET low_status_sent = 1, 
                        last_updated = ?
                    WHERE beacon_id = ?
                ''', (now, beacon_id))
                conn.commit()

            # 3. Сброс статуса при восстановлении
            elif low_status_sent and fuel_percent >= 20 and lifetime_percent >= 20:
                cursor.execute('''
                    UPDATE beacons 
                    SET low_status_sent = 0,
                        last_updated = ?
                    WHERE beacon_id = ?
                ''', (now, beacon_id))
                conn.commit()

                channel = bot.get_channel(1403035488591413268)
                await channel.send(
                    f"✅ Маяк {beacon_id} восстановил нормальные показатели"
                )

    except Exception as e:
        print(f"[ОШИБКА] check_beacons: {str(e)}")
        raise

    finally:
        conn.close()


# ============== ФУНКЦИИ ДЛЯ АВТОДОПОЛНЕНИЯ ==============

async def get_beacon_ids(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Возвращает список ID маяков для автодополнения"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT beacon_id FROM beacons ORDER BY beacon_id')
        beacons = cursor.fetchall()

        # Фильтруем по введенному тексту
        choices = []
        for beacon in beacons:
            beacon_id = beacon['beacon_id']
            # Если ничего не введено или ID содержит введенный текст (без учета регистра)
            if not current or current.lower() in beacon_id.lower():
                choices.append(app_commands.Choice(name=beacon_id, value=beacon_id))

        # Discord ограничивает 25 вариантами
        return choices[:25]
    finally:
        conn.close()


async def get_beacon_ids_with_details(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Возвращает список ID маяков с дополнительной информацией для автодополнения"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT beacon_id, current_fuel, current_lifetime FROM beacons ORDER BY beacon_id')
        beacons = cursor.fetchall()

        choices = []
        for beacon in beacons:
            beacon_id = beacon['beacon_id']
            fuel = beacon['current_fuel']
            lifetime = beacon['current_lifetime']

            # Создаем название с информацией о состоянии
            display_name = f"{beacon_id} (🔋{fuel:.0f} | 🔄{lifetime:.0f}%)"

            if not current or current.lower() in beacon_id.lower() or current.lower() in display_name.lower():
                choices.append(app_commands.Choice(name=display_name[:100], value=beacon_id))

        return choices[:25]
    finally:
        conn.close()


# ============== КЛАССЫ ДЛЯ МОДАЛЬНЫХ ОКОН ==============

class AddBeaconModal(Modal, title="➕ Добавление маяка"):
    """Модальное окно для добавления маяка"""

    beacon_id = TextInput(
        label="ID маяка",
        placeholder="Например: BCN-001",
        required=True,
        max_length=20
    )

    priority = TextInput(
        label="Приоритет (1-3)",
        placeholder="1 - высокий, 2 - средний, 3 - низкий",
        required=True,
        default="2",
        max_length=1
    )

    fuel = TextInput(
        label=f"Топливо (0-{MAX_FUEL})",
        placeholder=f"Оставьте пустым для {MAX_FUEL}",
        required=False,
        max_length=3
    )

    lifetime = TextInput(
        label=f"Прочность (0-{MAX_LIFETIME}%)",
        placeholder=f"Оставьте пустым для {MAX_LIFETIME}",
        required=False,
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Проверка приоритета
        try:
            priority = int(self.priority.value)
            if priority not in [1, 2, 3]:
                await interaction.response.send_message(
                    "❌ Ошибка: приоритет должен быть 1, 2 или 3",
                    ephemeral=True
                )
                return
        except ValueError:
            await interaction.response.send_message(
                "❌ Ошибка: приоритет должен быть числом",
                ephemeral=True
            )
            return

        # Обработка значений
        current_fuel = float(self.fuel.value) if self.fuel.value else MAX_FUEL
        current_lifetime = float(self.lifetime.value) if self.lifetime.value else MAX_LIFETIME

        if current_fuel > MAX_FUEL or current_lifetime > MAX_LIFETIME:
            await interaction.response.send_message(
                f"❌ Ошибка: значения не могут превышать {MAX_FUEL} для топлива и {MAX_LIFETIME}% для срока",
                ephemeral=True
            )
            return

        if priority == 1:
            fuel_consumption_rate = 1
        elif priority == 2:
            fuel_consumption_rate = 1.5
        else:  # priority == 3
            fuel_consumption_rate = 2

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO beacons 
                (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate, last_updated, low_status_sent) 
                VALUES (?, ?, ?, ?, ?, ?)''',
                (self.beacon_id.value, current_fuel, current_lifetime, fuel_consumption_rate,
                 datetime.now().isoformat(), False)
            )
            conn.commit()

            priority_text = {1: "🔴 Высокий", 2: "🟡 Средний", 3: "🟢 Низкий"}[priority]

            embed = discord.Embed(
                title="✅ Маяк добавлен",
                description=f"**{self.beacon_id.value}**",
                color=discord.Color.green()
            )
            embed.add_field(name="🔋 Топливо", value=f"{current_fuel}/{MAX_FUEL}")
            embed.add_field(name="🔄 Прочность", value=f"{current_lifetime}%")
            embed.add_field(name="📊 Приоритет", value=priority_text)

            await interaction.response.send_message(embed=embed)

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                f"❌ Маяк {self.beacon_id.value} уже существует!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
        finally:
            conn.close()


class RefuelModal(Modal, title="⛽ Заправка маяка"):
    """Модальное окно для заправки маяка"""

    def __init__(self, beacon_id: str = None):
        super().__init__()
        self.beacon_id_input = TextInput(
            label="ID маяка",
            placeholder="Например: BCN-001",
            required=True,
            max_length=20,
            default=beacon_id or ""
        )
        self.amount_input = TextInput(
            label=f"Количество топлива (0-{MAX_FUEL})",
            placeholder=f"Оставьте пустым для полной заправки ({MAX_FUEL})",
            required=False,
            max_length=3
        )
        self.add_item(self.beacon_id_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        amount = float(self.amount_input.value) if self.amount_input.value else MAX_FUEL

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT current_fuel FROM beacons WHERE beacon_id = ?',
                           (self.beacon_id_input.value,))
            result = cursor.fetchone()

            if not result:
                await interaction.response.send_message(
                    f"❌ Маяк {self.beacon_id_input.value} не найден!",
                    ephemeral=True
                )
                return

            current = float(result['current_fuel'])
            new_fuel = min(current + amount, MAX_FUEL)

            # Проверяем, нужно ли сбросить статус
            reset_status = (new_fuel / MAX_FUEL) * 100 >= 20

            cursor.execute('''
                UPDATE beacons 
                SET current_fuel = ?, 
                    last_updated = ?,
                    low_status_sent = ?
                WHERE beacon_id = ?
            ''', (new_fuel, datetime.now().isoformat(), not reset_status, self.beacon_id_input.value))

            conn.commit()

            embed = discord.Embed(
                title="⛽ Заправка выполнена",
                description=f"Маяк **{self.beacon_id_input.value}**",
                color=discord.Color.blue()
            )
            embed.add_field(name="Новое топливо", value=f"{new_fuel}/{MAX_FUEL}")
            embed.add_field(name="Добавлено", value=f"{new_fuel - current:.1f}")

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
        finally:
            conn.close()


class EditBeaconModal(Modal, title="✏️ Редактирование маяка"):
    """Модальное окно для редактирования маяка"""

    def __init__(self, beacon_id: str = None):
        super().__init__()
        self.beacon_id_input = TextInput(
            label="ID маяка",
            placeholder="Например: BCN-001",
            required=True,
            max_length=20,
            default=beacon_id or ""
        )
        self.priority_input = TextInput(
            label="Новый приоритет (1-3)",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=1
        )
        self.fuel_input = TextInput(
            label=f"Новое топливо (0-{MAX_FUEL})",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=3
        )
        self.lifetime_input = TextInput(
            label=f"Новая прочность (0-{MAX_LIFETIME}%)",
            placeholder="Оставьте пустым, если не меняете",
            required=False,
            max_length=3
        )

        self.add_item(self.beacon_id_input)
        self.add_item(self.priority_input)
        self.add_item(self.fuel_input)
        self.add_item(self.lifetime_input)

    async def on_submit(self, interaction: discord.Interaction):
        updates = []
        params = []
        reset_status = False

        # Обработка приоритета
        if self.priority_input.value:
            try:
                priority = int(self.priority_input.value)
                if priority not in [1, 2, 3]:
                    await interaction.response.send_message(
                        "❌ Ошибка: приоритет должен быть 1, 2 или 3",
                        ephemeral=True
                    )
                    return

                if priority == 1:
                    fuel_consumption_rate = 1
                elif priority == 2:
                    fuel_consumption_rate = 1.5
                else:
                    fuel_consumption_rate = 2

                updates.append("fuel_consumption_rate = ?")
                params.append(fuel_consumption_rate)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: приоритет должен быть числом",
                    ephemeral=True
                )
                return

        # Обработка топлива
        if self.fuel_input.value:
            try:
                new_fuel = float(self.fuel_input.value)
                if new_fuel > MAX_FUEL:
                    await interaction.response.send_message(
                        f"❌ Ошибка: топливо не может превышать {MAX_FUEL}",
                        ephemeral=True
                    )
                    return
                updates.append("current_fuel = ?")
                params.append(new_fuel)
                reset_status = reset_status or ((new_fuel / MAX_FUEL) * 100 >= 20)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: топливо должно быть числом",
                    ephemeral=True
                )
                return

        # Обработка прочности
        if self.lifetime_input.value:
            try:
                new_lifetime = float(self.lifetime_input.value)
                if new_lifetime > MAX_LIFETIME:
                    await interaction.response.send_message(
                        f"❌ Ошибка: прочность не может превышать {MAX_LIFETIME}%",
                        ephemeral=True
                    )
                    return
                updates.append("current_lifetime = ?")
                params.append(new_lifetime)
                reset_status = reset_status or (new_lifetime >= 20)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: прочность должна быть числом",
                    ephemeral=True
                )
                return

        if not updates:
            await interaction.response.send_message(
                "❌ Не указаны данные для обновления!",
                ephemeral=True
            )
            return

        # Добавляем обновление статуса уведомления
        updates.append("low_status_sent = ?")
        params.append(not reset_status)

        params.append(self.beacon_id_input.value)
        query = f"UPDATE beacons SET {', '.join(updates)}, last_updated = CURRENT_TIMESTAMP WHERE beacon_id = ?"

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()

            if cursor.rowcount == 0:
                await interaction.response.send_message(
                    f"❌ Маяк {self.beacon_id_input.value} не найден!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"✅ Данные маяка {self.beacon_id_input.value} успешно обновлены!"
                )
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
        finally:
            conn.close()


class DeleteBeaconModal(Modal, title="🗑️ Удаление маяка"):
    """Модальное окно для удаления маяка с подтверждением имени"""

    def __init__(self, beacon_id: str = None):
        super().__init__()
        self.beacon_id = beacon_id  # Сохраняем ID маяка для проверки

        self.beacon_id_display = TextInput(
            label="ID маяка для удаления",
            placeholder="Например: BCN-001",
            required=True,
            max_length=20,
            default=beacon_id or "",
            style=discord.TextStyle.short
        )

        self.confirm_name = TextInput(
            label="Подтверждение (введите ТОЧНОЕ название маяка)",
            placeholder="Введите ID маяка для подтверждения удаления",
            required=True,
            max_length=20,
            style=discord.TextStyle.short
        )

        self.add_item(self.beacon_id_display)
        self.add_item(self.confirm_name)

    async def on_submit(self, interaction: discord.Interaction):
        # Получаем ID маяка из первого поля
        beacon_id = self.beacon_id_display.value

        # Проверяем, совпадает ли подтверждение с ID маяка
        if self.confirm_name.value != beacon_id:
            await interaction.response.send_message(
                f"❌ Ошибка подтверждения: введенное имя '{self.confirm_name.value}' не совпадает с ID маяка '{beacon_id}'",
                ephemeral=True
            )
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Проверяем, существует ли маяк
            cursor.execute('SELECT beacon_id FROM beacons WHERE beacon_id = ?', (beacon_id,))
            result = cursor.fetchone()

            if not result:
                await interaction.response.send_message(
                    f"❌ Маяк {beacon_id} не найден!",
                    ephemeral=True
                )
                return

            # Удаляем маяк
            cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
            conn.commit()

            embed = discord.Embed(
                title="✅ Маяк удалён",
                description=f"Маяк **{beacon_id}** успешно удалён",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при удалении: {str(e)}",
                ephemeral=True
            )
        finally:
            conn.close()


# ============== КЛАСС С ВЫПАДАЮЩИМ СПИСКОМ ==============

class BeaconSelectView(View):
    """View с выпадающим списком маяков"""

    def __init__(self, action_type: str, user_id: int):
        super().__init__(timeout=60)
        self.action_type = action_type
        self.user_id = user_id
        self.add_item(BeaconSelect(action_type))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяет, что взаимодействие происходит от того же пользователя"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Вы не можете использовать это меню!",
                ephemeral=True
            )
            return False
        return True


class BeaconSelect(Select):
    """Выпадающий список маяков"""

    def __init__(self, action_type: str):
        self.action_type = action_type

        # Получаем список маяков из БД
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT beacon_id, current_fuel, current_lifetime FROM beacons ORDER BY beacon_id')
        beacons = cursor.fetchall()
        conn.close()

        if not beacons:
            options = [
                discord.SelectOption(
                    label="Нет активных маяков",
                    value="none",
                    description="Сначала добавьте маяк",
                    emoji="⚠️"
                )
            ]
        else:
            options = []
            for beacon in beacons[:25]:  # Discord ограничивает 25 опциями
                beacon_id = beacon['beacon_id']
                fuel = beacon['current_fuel']
                lifetime = beacon['current_lifetime']

                # Выбираем эмодзи в зависимости от состояния
                if lifetime < 20 or (fuel / MAX_FUEL * 100) < 20:
                    emoji = "⚠️"
                elif lifetime < 50 or (fuel / MAX_FUEL * 100) < 50:
                    emoji = "⚡"
                else:
                    emoji = "✅"

                options.append(
                    discord.SelectOption(
                        label=beacon_id,
                        value=beacon_id,
                        description=f"🔋{fuel:.0f}/{MAX_FUEL} | 🔄{lifetime:.0f}%",
                        emoji=emoji
                    )
                )

        super().__init__(
            placeholder="🔍 Выберите маяк из списка...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        """Обработка выбора"""
        if self.values[0] == "none":
            await interaction.response.send_message(
                "❌ Нет активных маяков. Сначала добавьте маяк через `/add`",
                ephemeral=True
            )
            return

        beacon_id = self.values[0]

        # Открываем соответствующее модальное окно
        if self.action_type == "refuel":
            await interaction.response.send_modal(RefuelModal(beacon_id))
        elif self.action_type == "edit":
            await interaction.response.send_modal(EditBeaconModal(beacon_id))
        elif self.action_type == "delete":
            await interaction.response.send_modal(DeleteBeaconModal(beacon_id))

        # Редактируем исходное сообщение, чтобы показать, что выбор сделан
        embed = discord.Embed(
            title="✅ Выбор сделан",
            description=f"Выбран маяк **{beacon_id}**",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=embed, view=None)


# ============== КЛАСС ДЛЯ МЕНЮ С КНОПКАМИ ==============

class BeaconMenuView(View):
    """Класс для создания меню с кнопками"""

    def __init__(self):
        super().__init__(timeout=60)  # Таймаут 60 секунд

    @discord.ui.button(label="➕ Добавить маяк", style=discord.ButtonStyle.green, emoji="➕", row=0)
    async def add_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка добавления маяка"""
        await interaction.response.send_modal(AddBeaconModal())

    @discord.ui.button(label="⛽ Заправить", style=discord.ButtonStyle.primary, emoji="⛽", row=0)
    async def refuel_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка заправки маяка с выбором из списка"""
        # Проверяем, есть ли маяки
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM beacons')
        count = cursor.fetchone()['count']
        conn.close()

        if count == 0:
            await interaction.response.send_message(
                "❌ Нет активных маяков для заправки!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="⛽ Заправка маяка",
            description="Выберите маяк из списка ниже:",
            color=discord.Color.blue()
        )

        view = BeaconSelectView("refuel", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="📊 Статус", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def status_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка просмотра статуса"""
        # Показываем статус всех маяков
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT * FROM beacons ORDER BY beacon_id')
            beacons = cursor.fetchall()

            if not beacons:
                await interaction.response.send_message(
                    "📭 Нет активных маяков",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="📊 Статус всех маяков",
                color=discord.Color.blue()
            )

            for beacon in beacons:
                if beacon['fuel_consumption_rate'] == 2:
                    priority_text = "🟢 Низкий(3)"
                elif beacon['fuel_consumption_rate'] == 1.5:
                    priority_text = "🟡 Средний(2)"
                elif beacon['fuel_consumption_rate'] == 1:
                    priority_text = "🔴 Высокий(1)"

                fuel_percent = (beacon['current_fuel'] / MAX_FUEL) * 100
                fuel_bar = "█" * int(fuel_percent / 10) + "░" * (10 - int(fuel_percent / 10))

                lifetime_bar = "█" * int(beacon['current_lifetime'] / 10) + "░" * (
                            10 - int(beacon['current_lifetime'] / 10))

                embed.add_field(
                    name=f"{beacon['beacon_id']} {priority_text}",
                    value=f"🔋 Топливо: {fuel_bar} {beacon['current_fuel']:.1f}/{MAX_FUEL}\n"
                          f"🔄 Прочность: {lifetime_bar} {beacon['current_lifetime']:.1f}%",
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
        finally:
            conn.close()

    @discord.ui.button(label="✏️ Редактировать", style=discord.ButtonStyle.secondary, emoji="✏️", row=1)
    async def edit_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка редактирования маяка с выбором из списка"""
        # Проверяем, есть ли маяки
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM beacons')
        count = cursor.fetchone()['count']
        conn.close()

        if count == 0:
            await interaction.response.send_message(
                "❌ Нет активных маяков для редактирования!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="✏️ Редактирование маяка",
            description="Выберите маяк из списка ниже:",
            color=discord.Color.blue()
        )

        view = BeaconSelectView("edit", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🗑️ Удалить", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка удаления маяка с выбором из списка"""
        # Проверяем, есть ли маяки
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM beacons')
        count = cursor.fetchone()['count']
        conn.close()

        if count == 0:
            await interaction.response.send_message(
                "❌ Нет активных маяков для удаления!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🗑️ Удаление маяка",
            description="Выберите маяк из списка ниже:",
            color=discord.Color.red()
        )

        view = BeaconSelectView("delete", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка обновления данных"""
        embed = discord.Embed(
            title="🔄 Данные обновлены",
            description="Последнее обновление выполнено",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="❓ Помощь", style=discord.ButtonStyle.secondary, emoji="❓", row=2)
    async def help_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка помощи"""
        embed = discord.Embed(
            title="❓ Помощь по командам",
            description="Как пользоваться ботом",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="📋 Доступные действия",
            value=(
                "**➕ Добавить маяк** - добавить новый маяк\n"
                "**⛽ Заправить** - пополнить топливо маяка (с выбором из списка)\n"
                "**📊 Статус** - показать статус всех маяков\n"
                "**✏️ Редактировать** - изменить данные маяка (с выбором из списка)\n"
                "**🗑️ Удалить** - удалить маяк (с выбором из списка)\n"
                "**🔄 Обновить** - обновить данные\n"
                "**🧹 Очистить всё** - удалить все маяки (админ)"
            ),
            inline=False
        )
        embed.add_field(
            name="⌨️ Текстовые команды",
            value=(
                "`/add [ID] [приоритет] [топливо] [прочность]`\n"
                "`/refuel [ID] [количество]` - ID можно выбрать из списка\n"
                "`/status [ID]`\n"
                "`/edit [ID] [приоритет] [топливо] [прочность]` - ID можно выбрать из списка\n"
                "`/delete [ID]` - ID можно выбрать из списка\n"
                "`/clear` - удалить все маяки (админ)\n"
                "`/menu` - показать это меню"
            ),
            inline=False
        )
        embed.set_footer(text="Нажмите на кнопки ниже для действий")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🧹 Очистить всё", style=discord.ButtonStyle.danger, emoji="⚠️", row=2)
    async def clear_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка очистки всех маяков (только для админов)"""
        # Проверка прав
        has_permission = False
        allowed_user_ids = [226751097295994881]

        if interaction.user.id in allowed_user_ids:
            has_permission = True
        elif (interaction.user.guild_permissions.administrator or
              interaction.user.guild_permissions.manage_guild or
              interaction.user.guild_permissions.manage_channels):
            has_permission = True

        if not has_permission:
            embed = discord.Embed(
                title="❌ Доступ запрещен",
                description="У вас нет прав для выполнения этой команды!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Создаем кнопки для подтверждения
        class ConfirmClearView(View):
            def __init__(self, original_user):
                super().__init__(timeout=30)
                self.original_user = original_user

            @discord.ui.button(label="Да, удалить всё", style=discord.ButtonStyle.danger, emoji="✅")
            async def confirm_button(self, btn_interaction: discord.Interaction, button: Button):
                if btn_interaction.user.id != self.original_user.id:
                    await btn_interaction.response.send_message(
                        "Вы не можете подтвердить чужую команду!",
                        ephemeral=True
                    )
                    return

                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM beacons')
                    conn.commit()

                    embed = discord.Embed(
                        title="✅ Успешно",
                        description="Все маяки успешно удалены!",
                        color=discord.Color.green()
                    )
                    await btn_interaction.response.edit_message(embed=embed, view=None)
                except Exception as e:
                    embed = discord.Embed(
                        title="❌ Ошибка",
                        description=f"Произошла ошибка при удалении: {str(e)}",
                        color=discord.Color.red()
                    )
                    await btn_interaction.response.edit_message(embed=embed, view=None)
                finally:
                    conn.close()

            @discord.ui.button(label="Нет, отмена", style=discord.ButtonStyle.secondary, emoji="❌")
            async def cancel_button(self, btn_interaction: discord.Interaction, button: Button):
                if btn_interaction.user.id != self.original_user.id:
                    await btn_interaction.response.send_message(
                        "Вы не можете отменить чужую команду!",
                        ephemeral=True
                    )
                    return

                embed = discord.Embed(
                    title="❌ Отменено",
                    description="Очистка маяков отменена.",
                    color=discord.Color.red()
                )
                await btn_interaction.response.edit_message(embed=embed, view=None)

            async def on_timeout(self):
                for item in self.children:
                    item.disabled = True
                try:
                    embed = discord.Embed(
                        title="⌛ Время истекло",
                        description="Время подтверждения истекло. Очистка отменена.",
                        color=discord.Color.orange()
                    )
                    await interaction.edit_original_response(embed=embed, view=self)
                except:
                    pass

        embed = discord.Embed(
            title="⚠️ Подтверждение действия",
            description="Вы уверены, что хотите удалить **ВСЕ** маяки?\nЭто действие нельзя отменить!",
            color=discord.Color.yellow()
        )
        embed.set_footer(text="У вас есть 30 секунд на подтверждение")

        view = ConfirmClearView(interaction.user)
        await interaction.response.send_message(embed=embed, view=view)


# ============== КОМАНДЫ БОТА ==============

@bot.tree.command(name="menu", description="Показать меню управления маяками")
async def menu(interaction: discord.Interaction):
    """Показать меню с кнопками для управления маяками"""
    embed = discord.Embed(
        title="🚀 Управление маяками",
        description="Выберите действие с помощью кнопок ниже",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📋 Доступные действия",
        value=(
            "**➕ Добавить маяк** - добавить новый маяк\n"
            "**⛽ Заправить** - пополнить топливо маяка (с выбором из списка)\n"
            "**📊 Статус** - показать статус всех маяков\n"
            "**✏️ Редактировать** - изменить данные маяка (с выбором из списка)\n"
            "**🗑️ Удалить** - удалить маяк (с выбором из списка)\n"
            "**🔄 Обновить** - обновить данные\n"
            "**❓ Помощь** - подробная информация\n"
            "**🧹 Очистить всё** - удалить все маяки (админ)"
        ),
        inline=False
    )
    embed.set_footer(text="Нажмите на кнопку для выполнения действия")

    view = BeaconMenuView()
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="add", description="Добавить новый маяк")
async def add(interaction: discord.Interaction, beacon_id: str = None, priority: int = 2,
              current_fuel: float = None, current_lifetime: float = None):
    """Добавить новый маяк
    Пример: !add BCN-001 30 100 2
    Приоритет: 1 - высокий, 2 - средний, 3 - низкий (по умолчанию 2)
    """
    # Если ID не указан, показываем меню
    if beacon_id is None:
        embed = discord.Embed(
            title="🚀 Управление маяками",
            description="Выберите действие с помощью кнопок ниже",
            color=discord.Color.blue()
        )
        view = BeaconMenuView()
        await interaction.response.send_message(embed=embed, view=view)
        return

    # Проверка приоритета
    if priority not in [1, 2, 3]:
        await interaction.response.send_message(
            "Ошибка: приоритет должен быть 1, 2 или 3\n"
            "1 - высокий\n2 - средний\n3 - низкий"
        )
        return

    current_fuel = current_fuel if current_fuel is not None else MAX_FUEL
    current_lifetime = current_lifetime if current_lifetime is not None else MAX_LIFETIME

    if priority == 1:
        fuel_consumption_rate = 1
    elif priority == 2:
        fuel_consumption_rate = 1.5
    elif priority == 3:
        fuel_consumption_rate = 2
    else:
        fuel_consumption_rate = 1.5

    if current_fuel > MAX_FUEL or current_lifetime > MAX_LIFETIME:
        await interaction.response.send_message(
            f"Ошибка: значения не могут превышать {MAX_FUEL} для топлива и {MAX_LIFETIME}% для срока"
        )
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO beacons 
            (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate, last_updated, low_status_sent) 
            VALUES (?, ?, ?, ?, ?, ?)''',
            (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate,
             datetime.now().isoformat(), False)
        )
        conn.commit()

        # Текстовое представление приоритета
        priority_text = {1: "🔴 Высокий", 2: "🟡 Средний", 3: "🟢 Низкий"}[priority]

        await interaction.response.send_message(
            f"Маяк {beacon_id} успешно добавлен\n"
            f"🔋 Топливо: {current_fuel}\n"
            f"🔄 Прочность: {current_lifetime}%\n"
            f"📊 Приоритет: {priority_text}"
        )
    except sqlite3.IntegrityError:
        await interaction.response.send_message(f"Маяк {beacon_id} уже существует!")
    except Exception as e:
        await interaction.response.send_message(f"Ошибка: {str(e)}")
    finally:
        conn.close()


@bot.tree.command(name="refuel", description="Пополнить топливо маяка")
@app_commands.autocomplete(beacon_id=get_beacon_ids_with_details)
async def refuel(interaction: discord.Interaction, beacon_id: str = None, amount: float = None):
    """Пополнить топливо маяка по ID с автодополнением"""
    if beacon_id is None:
        # Показываем меню с выбором
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM beacons')
        count = cursor.fetchone()['count']
        conn.close()

        if count == 0:
            await interaction.response.send_message(
                "❌ Нет активных маяков для заправки!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="⛽ Заправка маяка",
            description="Выберите маяк из списка ниже:",
            color=discord.Color.blue()
        )

        view = BeaconSelectView("refuel", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    if amount is None:
        amount = MAX_FUEL

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT current_fuel FROM beacons WHERE beacon_id = ?', (beacon_id,))
        result = cursor.fetchone()

        if not result:
            await interaction.response.send_message(f"Маяк {beacon_id} не найден!")
            return

        current = float(result['current_fuel'])
        new_fuel = min(current + amount, MAX_FUEL)

        # Проверяем, нужно ли сбросить статус
        reset_status = (new_fuel / MAX_FUEL) * 100 >= 20

        cursor.execute('''
            UPDATE beacons 
            SET current_fuel = ?, 
                last_updated = ?,
                low_status_sent = ?
            WHERE beacon_id = ?
        ''', (new_fuel, datetime.now().isoformat(), not reset_status, beacon_id))

        conn.commit()
        await interaction.response.send_message(
            f"Топливо маяка {beacon_id} пополнено до {new_fuel}/{MAX_FUEL}"
        )
    except Exception as e:
        await interaction.response.send_message(f"Ошибка: {str(e)}")
    finally:
        conn.close()


@bot.tree.command(name="status", description="Показать статус маяка")
@app_commands.autocomplete(beacon_id=get_beacon_ids)
async def status(interaction: discord.Interaction, beacon_id: str = None):
    """Показать статус маяка по ID или всех маяков с автодополнением"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if beacon_id:
            cursor.execute('SELECT * FROM beacons WHERE beacon_id = ?', (beacon_id,))
            beacon = cursor.fetchone()

            if not beacon:
                await interaction.response.send_message(
                    f"Маяк {beacon_id} не найден или уже сгнил!"
                )
                return

            hours_remaining_fuel = beacon['current_fuel'] * beacon['fuel_consumption_rate']
            hours_remaining_lifetime = beacon['current_lifetime'] / LIFETIME_DECAY_RATE

            if beacon['fuel_consumption_rate'] == 2:
                priority_text = "🟢 Низкий(3)"
            elif beacon['fuel_consumption_rate'] == 1.5:
                priority_text = "🟡 Средний(2)"
            elif beacon['fuel_consumption_rate'] == 1:
                priority_text = "🔴 Высокий(1)"

            # Специальное сообщение для почти сгнивших маяков
            if beacon['current_lifetime'] <= 5:
                status_msg = "🔴 КРИТИЧЕСКИЙ УРОВЕНЬ - скоро сгниет!"
            else:
                status_msg = f"⏳ осталось ~{hours_remaining_lifetime:.1f} часов"

            await interaction.response.send_message(
                f"Статус маяка {beacon['beacon_id']}:\n"
                f"🔋 Топливо: ~{beacon['current_fuel']:.0f} "
                f"(⏳ Осталось ~{hours_remaining_fuel:.1f} часов)\n"
                f"🔄 Прочность: {beacon['current_lifetime']:.2f}% ({status_msg})\n"
                f"📊 Приоритет: {priority_text}"
            )

        else:
            cursor.execute('SELECT * FROM beacons ORDER BY beacon_id')
            beacons = cursor.fetchall()

            if not beacons:
                await interaction.response.send_message("Нет активных маяков")
                return

            embed = discord.Embed(
                title="📊 Статус всех маяков",
                color=discord.Color.blue()
            )

            for beacon in beacons:
                if beacon['fuel_consumption_rate'] == 2:
                    priority_text = "🟢 Низкий(3)"
                elif beacon['fuel_consumption_rate'] == 1.5:
                    priority_text = "🟡 Средний(2)"
                elif beacon['fuel_consumption_rate'] == 1:
                    priority_text = "🔴 Высокий(1)"

                fuel_percent = (beacon['current_fuel'] / MAX_FUEL) * 100
                fuel_bar = "█" * int(fuel_percent / 10) + "░" * (10 - int(fuel_percent / 10))

                lifetime_bar = "█" * int(beacon['current_lifetime'] / 10) + "░" * (
                            10 - int(beacon['current_lifetime'] / 10))

                embed.add_field(
                    name=f"{beacon['beacon_id']} {priority_text}",
                    value=f"🔋 Топливо: {fuel_bar} {beacon['current_fuel']:.1f}/{MAX_FUEL}\n"
                          f"🔄 Прочность: {lifetime_bar} {beacon['current_lifetime']:.1f}%",
                    inline=False
                )

            await interaction.response.send_message(embed=embed)

    except Exception as e:
        await interaction.response.send_message(f"Ошибка: {str(e)}")
    finally:
        conn.close()


@bot.tree.command(name="edit", description="Редактировать данные маяка")
@app_commands.autocomplete(beacon_id=get_beacon_ids_with_details)
async def edit(interaction: discord.Interaction, beacon_id: str = None, priority: int = 2,
               current_fuel: float = None, current_lifetime: float = None):
    """Редактировать данные маяка по ID с автодополнением"""
    if beacon_id is None:
        # Показываем меню с выбором
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM beacons')
        count = cursor.fetchone()['count']
        conn.close()

        if count == 0:
            await interaction.response.send_message(
                "❌ Нет активных маяков для редактирования!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="✏️ Редактирование маяка",
            description="Выберите маяк из списка ниже:",
            color=discord.Color.blue()
        )

        view = BeaconSelectView("edit", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    updates = []
    params = []
    reset_status = False

    if priority is not None:
        if priority not in [1, 2, 3]:
            await interaction.response.send_message(
                "Ошибка: приоритет должен быть 1, 2 или 3\n"
                "1 - высокий\n2 - средний\n3 - низкий"
            )
            return
        # Вычисляем новый расход топлива
        if priority == 1:
            fuel_consumption_rate = 1
        elif priority == 2:
            fuel_consumption_rate = 1.5
        else:  # priority == 3
            fuel_consumption_rate = 2
        updates.append("fuel_consumption_rate = ?")
        params.append(fuel_consumption_rate)

    if current_fuel is not None:
        if current_fuel > MAX_FUEL:
            await interaction.response.send_message(
                f"Ошибка: значение топлива не может превышать {MAX_FUEL}"
            )
            return
        updates.append("current_fuel = ?")
        params.append(current_fuel)
        reset_status = reset_status or ((current_fuel / MAX_FUEL) * 100 >= 20)

    if current_lifetime is not None:
        if current_lifetime > MAX_LIFETIME:
            await interaction.response.send_message(
                f"Ошибка: срок действия не может превышать {MAX_LIFETIME}"
            )
            return
        updates.append("current_lifetime = ?")
        params.append(current_lifetime)
        reset_status = reset_status or (current_lifetime >= 20)

    if not updates:
        await interaction.response.send_message("Не указаны данные для обновления!")
        return

    # Добавляем обновление статуса уведомления
    updates.append("low_status_sent = ?")
    params.append(not reset_status)

    params.append(beacon_id)
    query = f"UPDATE beacons SET {', '.join(updates)}, last_updated = CURRENT_TIMESTAMP WHERE beacon_id = ?"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()

        if cursor.rowcount == 0:
            await interaction.response.send_message(f"Маяк {beacon_id} не найден!")
        else:
            await interaction.response.send_message(f"Данные маяка {beacon_id} успешно обновлены!")
    finally:
        conn.close()


@bot.tree.command(name="delete", description="Удалить маяк по ID")
@app_commands.autocomplete(beacon_id=get_beacon_ids_with_details)
async def delete(interaction: discord.Interaction, beacon_id: str = None):
    """Удалить маяк по ID с автодополнением"""
    if beacon_id is None:
        # Показываем меню с выбором
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM beacons')
        count = cursor.fetchone()['count']
        conn.close()

        if count == 0:
            await interaction.response.send_message(
                "❌ Нет активных маяков для удаления!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🗑️ Удаление маяка",
            description="Выберите маяк из списка ниже:",
            color=discord.Color.red()
        )

        view = BeaconSelectView("delete", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
    conn.commit()

    if cursor.rowcount == 0:
        await interaction.response.send_message(f"Маяк с ID {beacon_id} не найден!")
    else:
        await interaction.response.send_message(f"Маяк {beacon_id} успешно удалён!")

    conn.close()


# TODO вынести View отдельно
@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction):
    """Удалить все маяки (требуется подтверждение)"""
    has_permission = False
    allowed_user_ids = [226751097295994881]

    if interaction.user.id in allowed_user_ids:
        has_permission = True
        print(f"Доступ разрешен по ID: {interaction.user.id}")

    elif (interaction.user.guild_permissions.administrator or
          interaction.user.guild_permissions.manage_guild or
          interaction.user.guild_permissions.manage_channels):
        has_permission = True

    if not has_permission:
        embed = discord.Embed(
            title="❌ Доступ запрещен",
            description="У вас нет прав для выполнения этой команды!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Создаем кнопки для подтверждения
    class ConfirmView(View):
        def __init__(self):
            super().__init__(timeout=30)

        @discord.ui.button(label="Да", style=discord.ButtonStyle.green, emoji="✅")
        async def confirm_button(self, button_interaction: discord.Interaction, button: Button):
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message(
                    "Вы не можете подтвердить чужую команду!",
                    ephemeral=True
                )
                return

            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('DELETE FROM beacons')
                conn.commit()

                embed = discord.Embed(
                    title="✅ Успешно",
                    description="Все маяки успешно удалены!",
                    color=discord.Color.green()
                )
                await button_interaction.response.edit_message(embed=embed, view=None)
            except Exception as e:
                embed = discord.Embed(
                    title="❌ Ошибка",
                    description=f"Произошла ошибка при удалении: {str(e)}",
                    color=discord.Color.red()
                )
                await button_interaction.response.edit_message(embed=embed, view=None)
            finally:
                conn.close()

        @discord.ui.button(label="Нет", style=discord.ButtonStyle.red, emoji="❌")
        async def cancel_button(self, button_interaction: discord.Interaction, button: Button):
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message(
                    "Вы не можете отменить чужую команду!",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="❌ Отменено",
                description="Очистка маяков отменена.",
                color=discord.Color.red()
            )
            await button_interaction.response.edit_message(embed=embed, view=None)

        async def on_timeout(self):
            # При таймауте деактивируем кнопки
            for item in self.children:
                item.disabled = True
            try:
                embed = discord.Embed(
                    title="⌛ Время истекло",
                    description="Время подтверждения истекло. Очистка отменена.",
                    color=discord.Color.orange()
                )
                await interaction.edit_original_response(embed=embed, view=self)
            except:
                pass

    # Создаем embed с запросом подтверждения
    embed = discord.Embed(
        title="⚠️ Подтверждение действия",
        description="Вы уверены, что хотите удалить **ВСЕ** маяки?\nЭто действие нельзя отменить!",
        color=discord.Color.yellow()
    )
    embed.set_footer(text="У вас есть 30 секунд на подтверждение")

    # Отправляем сообщение с кнопками
    view = ConfirmView()
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
    """Бот жив?"""
    await interaction.response.send_message("pong")


bot.run(os.getenv("TOKEN"))