import os
import sqlite3
from datetime import datetime
from typing import List
import logging
from logging.handlers import RotatingFileHandler

import discord
from discord.ui import Button, View, Modal, TextInput, Select
from discord.ext import tasks
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
LOG_DIR = './logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Формат логов
log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Основной логгер для действий
action_logger = logging.getLogger('beacon_actions')
action_handler = RotatingFileHandler(
    f'{LOG_DIR}/actions.log',
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
action_handler.setFormatter(log_formatter)
action_logger.addHandler(action_handler)
action_logger.setLevel(logging.INFO)

# Логгер для ошибок
error_logger = logging.getLogger('beacon_errors')
error_handler = RotatingFileHandler(
    f'{LOG_DIR}/errors.log',
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
error_handler.setFormatter(log_formatter)
error_logger.addHandler(error_handler)
error_logger.setLevel(logging.ERROR)

# Функция для получения информации о пользователе
def get_user_info(interaction):
    """Возвращает строку с информацией о пользователе"""
    return f"User: {interaction.user.name} (ID: {interaction.user.id})"


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
            current_fuel REAL NOT NULL,  -- меняем на REAL
            current_lifetime REAL NOT NULL,  -- меняем на REAL
            fuel_consumption_rate REAL NOT NULL,  -- меняем на REAL
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            low_status_sent BOOLEAN DEFAULT FALSE,
            message_link TEXT
        )
    ''')

    # Проверяем, существует ли колонка message_link
    cursor.execute("PRAGMA table_info(beacons)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'message_link' not in columns:
        cursor.execute("ALTER TABLE beacons ADD COLUMN message_link TEXT")
        conn.commit()

    conn.commit()
    conn.close()

init_db()

def get_user_info(interaction):
    """Возвращает строку с информацией о пользователе"""
    return f"User: {interaction.user.name} (ID: {interaction.user.id})"

@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    action_logger.info(f'Bot {bot.user} started!')
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
    updated_count = 0

    for beacon in beacons:
        hours_passed = calculate_decay(beacon['last_updated'])

        if hours_passed <= 0:
            continue

        # Правильный расчет расхода топлива
        # fuel_consumption_rate: 1 (быстрый), 1.5 (средний), 2 (медленный)
        # Чем выше число, тем медленнее расход
        fuel_consumption_per_hour = 1 / beacon['fuel_consumption_rate']
        new_fuel = float(beacon['current_fuel']) - (fuel_consumption_per_hour * hours_passed)

        # Расчет износа
        new_lifetime = float(beacon['current_lifetime']) - (LIFETIME_DECAY_RATE * hours_passed)

        old_fuel = beacon['current_fuel']
        old_lifetime = beacon['current_lifetime']
        new_fuel = max(0, new_fuel)
        new_lifetime = max(0, new_lifetime)

        # Логируем изменения
        if old_fuel - new_fuel > 1.5 or old_lifetime - new_lifetime > 5:
            action_logger.debug(
                f"Auto-update beacon {beacon['beacon_id']}: "
                f"Hours passed: {hours_passed:.2f}, "
                f"Fuel: {old_fuel:.1f}→{new_fuel:.1f}, "
                f"Lifetime: {old_lifetime:.1f}→{new_lifetime:.1f}"
            )

        cursor.execute('''
            UPDATE beacons 
            SET current_fuel = ?, current_lifetime = ?, last_updated = ?
            WHERE id = ?
        ''', (new_fuel, new_lifetime, now, beacon['id']))
        updated_count += 1

    conn.commit()
    conn.close()

    if updated_count > 0:
        action_logger.debug(f"Auto-update completed for {updated_count} beacons")


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
                low_status_sent = False

            now = datetime.now().isoformat()

            # 1. Проверка на полностью сгнившие маяки (lifetime <= 0)
            if current_lifetime <= 0:
                channel = bot.get_channel(int(os.getenv("ALERT_ROLE_ID")))
                await channel.send(
                    f"🗑️ Маяк {beacon_id} полностью сгнил и был автоматически удалён"
                )
                action_logger.info(f"Auto-deleted beacon {beacon_id}: lifetime reached 0")
                cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
                conn.commit()
                continue

            # 2. Проверка низких показателей
            fuel_percent = (current_fuel / MAX_FUEL) * 100
            lifetime_percent = current_lifetime

            if (fuel_percent < 20 or lifetime_percent < 20) and not low_status_sent:
                channel = bot.get_channel(int(os.getenv("ALERT_ROLE_ID")))

                # Определяем уровень критичности
                is_critical = (fuel_percent < 5 or lifetime_percent < 5)
                warning_emoji = "💀" if is_critical else "⚠️"
                warning_text = "КРИТИЧЕСКИЙ УРОВЕНЬ!" if is_critical else "ВНИМАНИЕ!"

                # Создаем полоски прогресса
                fuel_bar = "█" * int(fuel_percent / 10) + "░" * (10 - int(fuel_percent / 10))
                lifetime_bar = "█" * int(current_lifetime / 10) + "░" * (10 - int(current_lifetime / 10))

                # Добавляем эмодзи для показателей
                fuel_emoji = "💀" if fuel_percent < 5 else "🟡" if fuel_percent < 20 else "✅"
                lifetime_emoji = "💀" if lifetime_percent < 5 else "🟡" if lifetime_percent < 20 else "✅"

                embed = discord.Embed(
                    title=f"{warning_emoji} {warning_text}",
                    description=f"Маяк **{beacon_id}**",
                    color=discord.Color.red() if is_critical else discord.Color.orange(),
                    timestamp=datetime.now()
                )

                # Добавляем поля с полосками прогресса
                embed.add_field(
                    name=f"{fuel_emoji} Топливо",
                    value=f"🔋 {fuel_bar} {current_fuel:.1f}/{MAX_FUEL} ({fuel_percent:.1f}%)",
                    inline=False
                )

                embed.add_field(
                    name=f"{lifetime_emoji} Прочность",
                    value=f"🔄 {lifetime_bar} {current_lifetime:.1f}%",
                    inline=False
                )

                # Добавляем ссылку на исходное сообщение
                if beacon['message_link']:
                    embed.add_field(name="", value=f"🔗 [Перейти]({beacon['message_link']})", inline=False)

                await channel.send(embed=embed)

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

                # Создаем embed для восстановления
                fuel_percent = (current_fuel / MAX_FUEL) * 100
                fuel_bar = "█" * int(fuel_percent / 10) + "░" * (10 - int(fuel_percent / 10))
                lifetime_bar = "█" * int(current_lifetime / 10) + "░" * (10 - int(current_lifetime / 10))

                embed = discord.Embed(
                    title="✅ Маяк восстановил нормальные показатели",
                    description=f"Маяк **{beacon_id}**",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )

                embed.add_field(
                    name="🔋 Топливо",
                    value=f"{fuel_bar} {current_fuel:.1f}/{MAX_FUEL} ({fuel_percent:.1f}%)",
                    inline=False
                )

                embed.add_field(
                    name="🔄 Прочность",
                    value=f"{lifetime_bar} {current_lifetime:.1f}%",
                    inline=False
                )

                if beacon['message_link']:
                    embed.add_field(name="", value=f"🔗 [Перейти]({beacon['message_link']})", inline=False)

                await channel.send(embed=embed)

                action_logger.info(f"Beacon {beacon_id} recovered to normal status")

    except Exception as e:
        error_msg = f"Ошибка в check_beacons: {str(e)}"
        error_logger.error(error_msg, exc_info=True)
        print(f"[ОШИБКА] {error_msg}")
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
        cursor.execute('SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate FROM beacons ORDER BY beacon_id')
        beacons = cursor.fetchall()

        choices = []
        for beacon in beacons:
            beacon_id = beacon['beacon_id']
            fuel = beacon['current_fuel']
            lifetime = beacon['current_lifetime']
            rate = beacon['fuel_consumption_rate']

            # Выбираем эмодзи приоритета
            if rate == 1:
                priority_emoji = "🔴"  # Высокий приоритет
            elif rate == 1.5:
                priority_emoji = "🟡"  # Средний приоритет
            else:  # rate == 2
                priority_emoji = "🟢"  # Низкий приоритет

            # Создаем название с эмодзи приоритета
            display_name = f"{priority_emoji} {beacon_id} (🔋{fuel:.0f} | 🔄{lifetime:.0f}%)"

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
        user_info = get_user_info(interaction)

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
            # Сначала создаем embed и отправляем сообщение, чтобы получить ссылку
            priority_text = {1: "🔴 Высокий", 2: "🟡 Средний", 3: "🟢 Низкий"}[priority]

            embed = discord.Embed(
                title="✅ Добавлен маяк",
                description=f"**{self.beacon_id.value}**",
                color=discord.Color.green()
            )
            embed.add_field(name="🔋 Топливо", value=f"{current_fuel}/{MAX_FUEL}")
            embed.add_field(name="🔄 Прочность", value=f"{current_lifetime}%")
            embed.add_field(name="📊 Приоритет", value=priority_text)
            embed.add_field(name="", value=f"Добавил: {interaction.user.mention}", inline=False)

            # Отправляем сообщение в канал
            sent_message = await interaction.channel.send(embed=embed)

            # Сохраняем ссылку на сообщение
            message_link = sent_message.jump_url

            # Теперь сохраняем в базу данных с ссылкой
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO beacons 
                (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate, last_updated, low_status_sent, message_link) 
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (self.beacon_id.value, current_fuel, current_lifetime, fuel_consumption_rate,
                 datetime.now().isoformat(), False, message_link)
            )
            conn.commit()

            # Логируем успешное добавление
            action_logger.info(
                f"{user_info} modal added beacon {self.beacon_id.value} | "
                f"Fuel: {current_fuel}/{MAX_FUEL}, Lifetime: {current_lifetime}%, Priority: {priority}"
            )

            # Отправляем подтверждение пользователю
            await interaction.response.send_message(
                f"✅ Маяк {self.beacon_id.value} успешно добавлен!",
                ephemeral=True
            )

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                f"❌ Маяк {self.beacon_id.value} уже существует!",
                ephemeral=True
            )
        except Exception as e:
            error_msg = f"Ошибка в modal add: {str(e)}"
            error_logger.error(f"{user_info} {error_msg}", exc_info=True)
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
            # Получаем данные маяка
            cursor.execute('SELECT current_fuel, message_link FROM beacons WHERE beacon_id = ?',
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
            message_link = result['message_link']

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

            action_logger.info(
                f"{get_user_info(interaction)} modal refueled beacon {self.beacon_id_input.value} | "
                f"Added: {amount}, Old: {current:.1f}, New: {new_fuel:.1f}/{MAX_FUEL}"
            )

            # Создаем embed
            embed = discord.Embed(
                title="⛽ Заправлен маяк",
                description=f"**{self.beacon_id_input.value}**",
                color=discord.Color.blue()
            )
            embed.add_field(name="Новое топливо", value=f"{new_fuel}/{MAX_FUEL}")
            embed.add_field(name="Добавлено", value=f"{new_fuel - current:.1f}")

            # Добавляем ссылку
            if message_link:
                embed.add_field(name="", value=f"🔗 [Перейти]({message_link})", inline=False)

            embed.add_field(name="", value=f"Заправил: {interaction.user.mention}", inline=False)

            # Отправляем эфемерное подтверждение (закрывает модальное окно)
            await interaction.response.send_message(
                f"✅ Заправка маяка {self.beacon_id_input.value} выполнена!",
                ephemeral=True
            )

            # После закрытия модального окна отправляем embed в канал
            await interaction.channel.send(embed=embed)

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
        changes = []
        new_values = {}

        # Получаем текущие данные маяка для сравнения
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM beacons WHERE beacon_id = ?', (self.beacon_id_input.value,))
        current_beacon = cursor.fetchone()

        if not current_beacon:
            await interaction.response.send_message(
                f"❌ Маяк {self.beacon_id_input.value} не найден!",
                ephemeral=True
            )
            conn.close()
            return

        # Сохраняем текущие значения и ссылку
        old_fuel = float(current_beacon['current_fuel'])
        old_lifetime = float(current_beacon['current_lifetime'])
        old_rate = current_beacon['fuel_consumption_rate']
        message_link = current_beacon['message_link']

        # Обработка приоритета
        if self.priority_input.value:
            try:
                priority = int(self.priority_input.value)
                if priority not in [1, 2, 3]:
                    await interaction.response.send_message(
                        "❌ Ошибка: приоритет должен быть 1, 2 или 3",
                        ephemeral=True
                    )
                    conn.close()
                    return

                if priority == 1:
                    fuel_consumption_rate = 1
                    new_priority_text = "🔴 Высокий"
                elif priority == 2:
                    fuel_consumption_rate = 1.5
                    new_priority_text = "🟡 Средний"
                else:
                    fuel_consumption_rate = 2
                    new_priority_text = "🟢 Низкий"

                updates.append("fuel_consumption_rate = ?")
                params.append(fuel_consumption_rate)

                old_priority_text = "🔴 Высокий" if old_rate == 1 else "🟡 Средний" if old_rate == 1.5 else "🟢 Низкий"
                changes.append(f"приоритет: {old_priority_text} → {new_priority_text}")
                new_values['priority'] = new_priority_text
                new_values['priority_rate'] = fuel_consumption_rate
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: приоритет должен быть числом",
                    ephemeral=True
                )
                conn.close()
                return
        else:
            if old_rate == 1:
                new_values['priority'] = "🔴 Высокий"
            elif old_rate == 1.5:
                new_values['priority'] = "🟡 Средний"
            else:
                new_values['priority'] = "🟢 Низкий"
            new_values['priority_rate'] = old_rate

        # Обработка топлива
        if self.fuel_input.value:
            try:
                new_fuel = float(self.fuel_input.value)
                if new_fuel > MAX_FUEL:
                    await interaction.response.send_message(
                        f"❌ Ошибка: топливо не может превышать {MAX_FUEL}",
                        ephemeral=True
                    )
                    conn.close()
                    return
                updates.append("current_fuel = ?")
                params.append(new_fuel)
                changes.append(f"топливо: {old_fuel:.1f} → {new_fuel:.1f}")
                new_values['fuel'] = new_fuel
                reset_status = reset_status or ((new_fuel / MAX_FUEL) * 100 >= 20)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: топливо должно быть числом",
                    ephemeral=True
                )
                conn.close()
                return
        else:
            new_values['fuel'] = old_fuel

        # Обработка прочности
        if self.lifetime_input.value:
            try:
                new_lifetime = float(self.lifetime_input.value)
                if new_lifetime > MAX_LIFETIME:
                    await interaction.response.send_message(
                        f"❌ Ошибка: прочность не может превышать {MAX_LIFETIME}%",
                        ephemeral=True
                    )
                    conn.close()
                    return
                updates.append("current_lifetime = ?")
                params.append(new_lifetime)
                changes.append(f"прочность: {old_lifetime:.1f}% → {new_lifetime:.1f}%")
                new_values['lifetime'] = new_lifetime
                reset_status = reset_status or (new_lifetime >= 20)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка: прочность должна быть числом",
                    ephemeral=True
                )
                conn.close()
                return
        else:
            new_values['lifetime'] = old_lifetime

        if not updates:
            await interaction.response.send_message(
                "❌ Не указаны данные для обновления!",
                ephemeral=True
            )
            conn.close()
            return

        # Добавляем обновление статуса уведомления
        updates.append("low_status_sent = ?")
        params.append(not reset_status)

        params.append(self.beacon_id_input.value)
        query = f"UPDATE beacons SET {', '.join(updates)}, last_updated = CURRENT_TIMESTAMP WHERE beacon_id = ?"

        try:
            cursor.execute(query, params)
            conn.commit()

            if cursor.rowcount == 0:
                await interaction.response.send_message(
                    f"❌ Маяк {self.beacon_id_input.value} не найден!",
                    ephemeral=True
                )
            else:
                # Создаем embed
                embed = discord.Embed(
                    title="✏️ Изменён маяк",
                    description=f"**{self.beacon_id_input.value}**",
                    color=discord.Color.gold(),
                    timestamp=datetime.now()
                )

                embed.add_field(
                    name="🔋 Топливо",
                    value=f"{new_values['fuel']:.1f}/{MAX_FUEL}",
                    inline=True
                )
                embed.add_field(
                    name="🔄 Прочность",
                    value=f"{new_values['lifetime']:.1f}%",
                    inline=True
                )
                embed.add_field(
                    name="📊 Приоритет",
                    value=new_values['priority'],
                    inline=True
                )

                if changes:
                    embed.add_field(
                        name="📝 Изменения",
                        value="\n".join([f"• {change}" for change in changes]),
                        inline=False
                    )

                if message_link:
                    embed.add_field(name="", value=f"🔗 [Перейти]({message_link})", inline=False)

                embed.add_field(name="", value=f"Отредактировал: {interaction.user.mention}", inline=False)

                # Отправляем эфемерное подтверждение (закрывает модальное окно)
                await interaction.response.send_message(
                    f"✅ Данные маяка {self.beacon_id_input.value} успешно обновлены!",
                    ephemeral=True
                )

                # После закрытия модального окна отправляем embed в канал
                await interaction.channel.send(embed=embed)

                # Логируем изменения
                action_logger.info(
                    f"{get_user_info(interaction)} modal edited beacon {self.beacon_id_input.value}: {', '.join(changes)}"
                )

        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
            error_logger.error(f"{get_user_info(interaction)} Ошибка при редактировании: {str(e)}", exc_info=True)
        finally:
            conn.close()


class DeleteBeaconModal(Modal, title="🗑️ Удаление маяка"):
    """Модальное окно для удаления маяка с подтверждением имени"""

    def __init__(self, beacon_id: str = None):
        super().__init__()
        self.beacon_id = beacon_id

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
        beacon_id = self.beacon_id_display.value

        if self.confirm_name.value != beacon_id:
            await interaction.response.send_message(
                f"❌ Ошибка подтверждения: введенное имя '{self.confirm_name.value}' не совпадает с ID маяка '{beacon_id}'",
                ephemeral=True
            )
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Получаем данные маяка
            cursor.execute(
                'SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate, message_link FROM beacons WHERE beacon_id = ?',
                (beacon_id,))
            result = cursor.fetchone()

            if not result:
                await interaction.response.send_message(
                    f"❌ Маяк {beacon_id} не найден!",
                    ephemeral=True
                )
                return

            current_fuel = result['current_fuel']
            current_lifetime = result['current_lifetime']
            rate = result['fuel_consumption_rate']
            message_link = result['message_link']

            if rate == 1:
                priority_text = "🔴 Высокий"
            elif rate == 1.5:
                priority_text = "🟡 Средний"
            else:
                priority_text = "🟢 Низкий"

            # Удаляем маяк
            cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
            conn.commit()

            # Создаем embed
            embed = discord.Embed(
                title="🗑️ Маяк удалён",
                description=f"**{beacon_id}**",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )

            embed.add_field(name="", value=f"Удалил: {interaction.user.mention}", inline=False)

            # Логируем удаление
            action_logger.info(
                f"{get_user_info(interaction)} modal deleted beacon {beacon_id} | "
                f"Fuel: {current_fuel}/{MAX_FUEL}, Lifetime: {current_lifetime}%, Priority: {priority_text}"
            )

            # Отправляем эфемерное подтверждение (закрывает модальное окно)
            await interaction.response.send_message(
                f"✅ Маяк {beacon_id} успешно удалён!",
                ephemeral=True
            )

            # После закрытия модального окна отправляем embed в канал
            await interaction.channel.send(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при удалении: {str(e)}",
                ephemeral=True
            )
            error_logger.error(f"{get_user_info(interaction)} Ошибка при удалении маяка {beacon_id}: {str(e)}",
                               exc_info=True)
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
        cursor.execute(
            'SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate FROM beacons ORDER BY beacon_id')
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

            # Добавляем опцию "Показать все" только для статуса
            if action_type == "status":
                options.append(
                    discord.SelectOption(
                        label="📊 Показать все маяки",
                        value="all",
                        description="Показать статус всех маяков",
                        emoji="📋"
                    )
                )

            for beacon in beacons[:24]:  # Оставляем место для опции "все"
                beacon_id = beacon['beacon_id']
                fuel = beacon['current_fuel']
                lifetime = beacon['current_lifetime']
                rate = beacon['fuel_consumption_rate']

                # Выбираем эмодзи приоритета
                if rate == 1:
                    emoji = "🔴"  # Высокий приоритет
                elif rate == 1.5:
                    emoji = "🟡"  # Средний приоритет
                else:  # rate == 2
                    emoji = "🟢"  # Низкий приоритет

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
        if self.values[0] == "none":
            await interaction.response.send_message(
                "❌ Нет активных маяков. Сначала добавьте маяк через `/add`",
                ephemeral=True
            )
            return

        beacon_id = self.values[0]

        # Обработка для статуса
        if self.action_type == "status":
            if beacon_id == "all":
                # Показать все маяки
                await show_all_beacons_status(interaction)
            else:
                # Показать статус конкретного маяка
                await show_beacon_status(interaction, beacon_id)
            return

        # Открываем соответствующее модальное окно для других действий
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


async def show_beacon_status(interaction: discord.Interaction, beacon_id: str):
    """Показать статус конкретного маяка"""
    user_info = get_user_info(interaction)
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM beacons WHERE beacon_id = ?', (beacon_id,))
        beacon = cursor.fetchone()

        if not beacon:
            await interaction.response.send_message(
                f"❌ Маяк {beacon_id} не найден!",
                ephemeral=True
            )
            return

        action_logger.info(f"{user_info} checked status of beacon {beacon_id}")

        hours_remaining_fuel = beacon['current_fuel'] * beacon['fuel_consumption_rate']
        hours_remaining_lifetime = beacon['current_lifetime'] / LIFETIME_DECAY_RATE

        if beacon['fuel_consumption_rate'] == 2:
            priority_text = "🟢 Низкий(3)"
        elif beacon['fuel_consumption_rate'] == 1.5:
            priority_text = "🟡 Средний(2)"
        elif beacon['fuel_consumption_rate'] == 1:
            priority_text = "🔴 Высокий(1)"

        if beacon['current_lifetime'] <= 5:
            status_msg = "💀 КРИТИЧЕСКИЙ УРОВЕНЬ - скоро сгниет!"
        else:
            status_msg = f"⏳ осталось ~{hours_remaining_lifetime:.1f} часов"

        embed = discord.Embed(
            title=f"📊 Статус маяка {beacon['beacon_id']}",
            description=f"Запросил: {interaction.user.mention}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(
            name="🔋 Топливо",
            value=f"~{beacon['current_fuel']:.0f} (⏳ ~{hours_remaining_fuel:.1f} ч)",
            inline=True
        )
        embed.add_field(
            name="🔄 Прочность",
            value=f"{beacon['current_lifetime']:.2f}%\n{status_msg}",
            inline=True
        )
        embed.add_field(
            name="📊 Приоритет",
            value=priority_text,
            inline=True
        )

        fuel_percent = (beacon['current_fuel'] / MAX_FUEL) * 100
        fuel_bar = "█" * int(fuel_percent / 10) + "░" * (10 - int(fuel_percent / 10))
        lifetime_bar = "█" * int(beacon['current_lifetime'] / 10) + "░" * (10 - int(beacon['current_lifetime'] / 10))

        embed.add_field(
            name="📊 Детально",
            value=f"🔋 {fuel_bar} {beacon['current_fuel']:.1f}/{MAX_FUEL}\n🔄 {lifetime_bar} {beacon['current_lifetime']:.1f}%",
            inline=False
        )

        # Добавляем ссылку на исходное сообщение
        if beacon['message_link']:
            embed.add_field(name="", value=f"🔗[Перейти]({beacon['message_link']})", inline=False)

        await interaction.response.send_message(
            f"✅ Статус маяка {beacon_id} отправлен в чат",
            ephemeral=True
        )

        await interaction.channel.send(embed=embed)

    except Exception as e:
        error_msg = f"Ошибка при просмотре статуса: {str(e)}"
        error_logger.error(f"{user_info} {error_msg}", exc_info=True)
        await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
    finally:
        conn.close()


async def show_all_beacons_status(interaction: discord.Interaction):
    """Показать статус всех маяков (публично)"""
    user_info = get_user_info(interaction)
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM beacons ORDER BY beacon_id')
        beacons = cursor.fetchall()

        if not beacons:
            action_logger.info(f"{user_info} checked status - no active beacons")
            await interaction.response.send_message(
                "📭 Нет активных маяков",
                ephemeral=True
            )
            return

        action_logger.info(f"{user_info} requested public status of all beacons ({len(beacons)} active)")

        embed = discord.Embed(
            title="📊 Статус всех маяков",
            description=f"Запросил: {interaction.user.mention}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        for beacon in beacons:
            if beacon['fuel_consumption_rate'] == 2:
                priority_text = "🟢"
            elif beacon['fuel_consumption_rate'] == 1.5:
                priority_text = "🟡"
            elif beacon['fuel_consumption_rate'] == 1:
                priority_text = "🔴"

            fuel_percent = (beacon['current_fuel'] / MAX_FUEL) * 100
            fuel_bar = "█" * int(fuel_percent / 10) + "░" * (10 - int(fuel_percent / 10))

            lifetime_bar = "█" * int(beacon['current_lifetime'] / 10) + "░" * (
                    10 - int(beacon['current_lifetime'] / 10))

            # Добавляем индикатор критического состояния
            status_emoji = ""
            if beacon['current_lifetime'] <= 20 or fuel_percent <= 20:
                status_emoji = "⚠️ "
            elif beacon['current_lifetime'] <= 5 or fuel_percent <= 5:
                status_emoji = "💀 "

            # Формируем имя поля с ссылкой "Перейти"
            field_value = f"🔋 {fuel_bar} {beacon['current_fuel']:.1f}/{MAX_FUEL}\n🔄 {lifetime_bar} {beacon['current_lifetime']:.1f}%"

            # Добавляем ссылку "Перейти" если есть
            if beacon['message_link']:
                field_value += f"\n[Перейти]({beacon['message_link']})"

            embed.add_field(
                name=f"{status_emoji}{priority_text} {beacon['beacon_id']}",
                value=field_value,
                inline=False
            )

        # Добавляем легенду
        embed.set_footer(text="🔴 Высокий | 🟡 Средний | 🟢 Низкий | ⚠️ Требует внимания")

        # Отправляем подтверждение пользователю
        await interaction.response.send_message(
            "✅ Статус всех маяков отправлен в чат",
            ephemeral=True
        )

        # Отправляем embed в канал
        await interaction.channel.send(embed=embed)

    except Exception as e:
        error_msg = f"Ошибка при просмотре статуса: {str(e)}"
        error_logger.error(f"{user_info} {error_msg}", exc_info=True)
        await interaction.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)
    finally:
        conn.close()


# ============== КЛАСС ДЛЯ МЕНЮ С КНОПКАМИ ==============

class BeaconMenuView(View):
    """Класс для создания меню с кнопками"""

    def __init__(self):
        super().__init__(timeout=120)  # Таймаут 60 секунд

    @discord.ui.button(label="Добавить маяк", style=discord.ButtonStyle.green, emoji="➕", row=0)
    async def add_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка добавления маяка"""
        await interaction.response.send_modal(AddBeaconModal())

    @discord.ui.button(label="Заправить", style=discord.ButtonStyle.primary, emoji="⛽", row=0)
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

    @discord.ui.button(label="Статус", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def status_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка просмотра статуса"""
        # Проверяем, есть ли маяки
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM beacons')
        count = cursor.fetchone()['count']
        conn.close()

        if count == 0:
            await interaction.response.send_message(
                "📭 Нет активных маяков",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📊 Просмотр статуса маяка",
            description="Выберите маяк для просмотра детального статуса\nили выберите 'Показать все маяки' для общего обзора",
            color=discord.Color.blue()
        )

        view = BeaconSelectView("status", interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Редактировать", style=discord.ButtonStyle.secondary, emoji="✏️", row=1)
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


    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
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

    @discord.ui.button(label="Обновить", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка обновления данных"""
        embed = discord.Embed(
            title="🔄 Данные обновлены",
            description="Последнее обновление выполнено",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # @discord.ui.button(label="Помощь", style=discord.ButtonStyle.secondary, emoji="❓", row=2)
    # async def help_button(self, interaction: discord.Interaction, button: Button):
    #     """Кнопка помощи"""
    #     embed = discord.Embed(
    #         title="❓ Помощь по командам",
    #         description="Как пользоваться ботом",
    #         color=discord.Color.purple()
    #     )
    #     embed.add_field(
    #         name="📋 Доступные действия",
    #         value=(
    #             "**➕ Добавить маяк** - добавить новый маяк\n"
    #             "**⛽ Заправить** - пополнить топливо маяка (с выбором из списка)\n"
    #             "**📊 Статус** - показать статус всех маяков\n"
    #             "**✏️ Редактировать** - изменить данные маяка (с выбором из списка)\n"
    #             "**🗑️ Удалить** - удалить маяк (с выбором из списка)\n"
    #             "**🔄 Обновить** - обновить данные\n"
    #             "**🧹 Очистить всё** - удалить все маяки (админ)"
    #         ),
    #         inline=False
    #     )
    #     embed.set_footer(text="Нажмите на кнопки ниже для действий")
    #
    #     await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Очистить всё", style=discord.ButtonStyle.danger, emoji="⚠️", row=2)
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
            def __init__(self, original_user, original_interaction):
                super().__init__(timeout=30)
                self.original_user = original_user
                self.original_interaction = original_interaction

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

                    # Получаем список маяков до удаления
                    cursor.execute(
                        'SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate FROM beacons')
                    beacons = cursor.fetchall()
                    beacon_list = [b['beacon_id'] for b in beacons]
                    count_before = len(beacon_list)

                    # Выполняем удаление
                    cursor.execute('DELETE FROM beacons')
                    conn.commit()

                    # ===== ЛОГИРОВАНИЕ ОЧИСТКИ =====
                    if count_before > 0:
                        action_logger.info(
                            f"{get_user_info(btn_interaction)} cleared ALL beacons via menu button | "
                            f"Deleted: {count_before} beacons: {', '.join(beacon_list)}"
                        )

                    # Создаем публичный embed об очистке
                    embed = discord.Embed(
                        title="🧹 Очистка всех маяков",
                        description=f"**Удалено маяков: {count_before}**",
                        color=discord.Color.red(),
                        timestamp=datetime.now()
                    )

                    if count_before > 0:
                        embed.add_field(
                            name="📋 Список удаленных маяков",
                            value=", ".join(beacon_list[:10]) + (
                                f" и еще {len(beacon_list) - 10}" if len(beacon_list) > 10 else ""),
                            inline=False
                        )

                    embed.add_field(name="", value=f"Очистил: {btn_interaction.user.mention}", inline=False)

                    # Отправляем публичное сообщение в канал
                    await btn_interaction.channel.send(embed=embed)

                    # Обновляем эфемерное сообщение
                    await btn_interaction.response.edit_message(
                        content=f"✅ Все маяки ({count_before}) успешно удалены!",
                        embed=None,
                        view=None
                    )

                except Exception as e:
                    error_msg = f"Ошибка при очистке всех маяков: {str(e)}"
                    error_logger.error(f"{get_user_info(btn_interaction)} {error_msg}", exc_info=True)
                    await btn_interaction.response.edit_message(
                        content=f"❌ Ошибка при удалении: {str(e)}",
                        embed=None,
                        view=None
                    )
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

                await btn_interaction.response.edit_message(
                    content="❌ Очистка маяков отменена.",
                    embed=None,
                    view=None
                )

            async def on_timeout(self):
                # При таймауте деактивируем кнопки
                for item in self.children:
                    item.disabled = True
                try:
                    # Обновляем эфемерное сообщение
                    await self.original_interaction.edit_original_response(
                        content="⌛ Время подтверждения истекло. Очистка отменена.",
                        embed=None,
                        view=self
                    )
                except:
                    pass

        # Создаем embed с запросом подтверждения
        embed = discord.Embed(
            title="⚠️ Подтверждение действия",
            description="Вы уверены, что хотите удалить **ВСЕ** маяки?\nЭто действие нельзя отменить!",
            color=discord.Color.yellow()
        )
        embed.set_footer(text="У вас есть 30 секунд на подтверждение")

        # Отправляем эфемерное сообщение с кнопками
        view = ConfirmClearView(interaction.user, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ============== КОМАНДЫ БОТА ==============

@bot.tree.command(name="menu", description="Показать меню управления маяками")
async def menu(interaction: discord.Interaction):
    """Показать меню с кнопками для управления маяками"""
    embed = discord.Embed(
        title="🚀 Управление маяками",
        color=discord.Color.blue()
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
        inline=False
    )

    view = BeaconMenuView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="add", description="Добавить новый маяк")
async def add(interaction: discord.Interaction):
    """Добавить новый маяк через модальное окно"""
    await interaction.response.send_modal(AddBeaconModal())


@bot.tree.command(name="refuel", description="Пополнить топливо маяка")
async def refuel(interaction: discord.Interaction):
    """Пополнить топливо маяка через интерфейс"""
    user_info = get_user_info(interaction)

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

@bot.tree.command(name="status", description="Показать статус маяка")
async def status(interaction: discord.Interaction):
    """Показать статус маяка через интерфейс выбора"""
    user_info = get_user_info(interaction)

    # Проверяем, есть ли маяки
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as count FROM beacons')
    count = cursor.fetchone()['count']
    conn.close()

    if count == 0:
        await interaction.response.send_message(
            "📭 Нет активных маяков",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📊 Просмотр статуса маяка",
        description="Выберите маяк для просмотра детального статуса\nили выберите 'Показать все маяки' для общего обзора",
        color=discord.Color.blue()
    )

    view = BeaconSelectView("status", interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="edit", description="Редактировать данные маяка")
async def edit(interaction: discord.Interaction):
    """Редактировать данные маяка через интерфейс"""
    user_info = get_user_info(interaction)

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

@bot.tree.command(name="delete", description="Удалить маяк")
async def delete(interaction: discord.Interaction):
    """Удалить маяк через интерфейс"""
    user_info = get_user_info(interaction)

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


@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction):
    """Удалить все маяки (требуется подтверждение)"""
    user_info = get_user_info(interaction)

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

                # Получаем список маяков до удаления
                cursor.execute('SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate FROM beacons')
                beacons = cursor.fetchall()
                beacon_list = [b['beacon_id'] for b in beacons]
                count_before = len(beacon_list)

                # Выполняем удаление
                cursor.execute('DELETE FROM beacons')
                conn.commit()

                # ===== ЛОГИРОВАНИЕ ОЧИСТКИ =====
                if count_before > 0:
                    action_logger.info(
                        f"{get_user_info(button_interaction)} cleared ALL beacons | "
                        f"Deleted: {count_before} beacons: {', '.join(beacon_list)}"
                    )

                # Создаем публичный embed об очистке
                embed = discord.Embed(
                    title="🧹 Очистка всех маяков",
                    description=f"**Удалено маяков: {count_before}**\nОчистил: {button_interaction.user.mention}",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )

                if count_before > 0:
                    embed.add_field(
                        name="📋 Список удаленных маяков",
                        value=", ".join(beacon_list[:10]) + (
                            f" и еще {len(beacon_list) - 10}" if len(beacon_list) > 10 else ""),
                        inline=False
                    )

                # Отправляем публичное сообщение в канал
                await button_interaction.channel.send(embed=embed)

                # Обновляем эфемерное сообщение
                await button_interaction.response.edit_message(
                    content=f"✅ Все маяки ({count_before}) успешно удалены!",
                    embed=None,
                    view=None
                )

            except Exception as e:
                error_msg = f"Ошибка при очистке всех маяков: {str(e)}"
                error_logger.error(f"{get_user_info(button_interaction)} {error_msg}", exc_info=True)
                await button_interaction.response.edit_message(
                    content=f"❌ Ошибка при удалении: {str(e)}",
                    embed=None,
                    view=None
                )
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

            await button_interaction.response.edit_message(
                content="❌ Очистка маяков отменена.",
                embed=None,
                view=None
            )

        async def on_timeout(self):
            # При таймауте деактивируем кнопки
            for item in self.children:
                item.disabled = True
            try:
                await interaction.edit_original_response(
                    content="⌛ Время подтверждения истекло. Очистка отменена.",
                    embed=None,
                    view=self
                )
            except:
                pass

    # Создаем embed с запросом подтверждения
    embed = discord.Embed(
        title="⚠️ Подтверждение действия",
        description="Вы уверены, что хотите удалить **ВСЕ** маяки?\nЭто действие нельзя отменить!",
        color=discord.Color.yellow()
    )
    embed.set_footer(text="У вас есть 30 секунд на подтверждение")

    # Отправляем сообщение с кнопками (эфемерное)
    view = ConfirmView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
    """Бот жив?"""
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)


bot.run(os.getenv("TOKEN"))