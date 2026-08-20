import os
import sqlite3
from datetime import datetime
from typing import List, Optional
import logging
from logging.handlers import RotatingFileHandler

import discord
from discord.ui import Button, View, Modal, TextInput, Select
import asyncio
from datetime import datetime, timedelta
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
    maxBytes=10 * 1024 * 1024,  # 10 MB
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
    maxBytes=10 * 1024 * 1024,  # 10 MB
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

RELIC_CHANNEL_ID = int(os.getenv("RELIC_CHANNEL_ID", 0))  # 0 если не задан

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


class RelicTimer:
    """Класс для управления таймером реликвии"""

    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        self.tasks = {}  # Словарь для хранения задач по каналам
        self.timer_messages = {}  # Словарь для хранения сообщений таймера
        self.timer_start_time = None  # Время запуска таймера
        self.timer_duration = None  # Длительность таймера в минутах

    async def start_timer(self, bot, minutes: int = 90):
        """Запустить таймер в указанном канале"""

        # Получаем канал по ID
        channel = bot.get_channel(self.channel_id)
        if not channel:
            error_logger.error(f"Channel {self.channel_id} not found for relic timer!")
            return None

        # Если уже есть таймер в этом канале, отменяем его
        if self.channel_id in self.tasks:
            self.tasks[self.channel_id].cancel()
            del self.tasks[self.channel_id]

        # Сохраняем время запуска и длительность
        self.timer_start_time = datetime.now()
        self.timer_duration = minutes

        # Создаем задачу
        task = asyncio.create_task(self._run_timer(bot, minutes))
        self.tasks[self.channel_id] = task

        # Логируем запуск таймера
        action_logger.info(
            f"Relic timer started in channel {channel.name} (ID: {self.channel_id}) for {minutes} minutes")

        return task

    async def _run_timer(self, bot, minutes: int):
        """Основная логика таймера"""
        try:
            # Получаем канал
            channel = bot.get_channel(self.channel_id)
            if not channel:
                error_logger.error(f"Channel {self.channel_id} not found for relic timer!")
                return

            # Ждем указанное время минус 10 минут
            wait_time = (minutes - 10) * 60  # переводим в секунды
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            # Получаем канал еще раз (на случай перезагрузки)
            channel = bot.get_channel(self.channel_id)
            if not channel:
                error_logger.error(f"Channel {self.channel_id} not found for relic timer!")
                return

            # Отправляем предупреждение за 10 минут
            embed = discord.Embed(
                title="⚔️ РЕЛИКВИЯ СКОРО ПОЯВИТСЯ!",
                description="Через ~10 минут появится реликвия. Вооружайтесь и будьте готовы к бою!",
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="⏰ Время до появления",
                value=f"**~10 минут**",
                inline=True
            )
            embed.add_field(
                name="📢 Приготовьтесь!",
                value="Соберите команду и подготовьте снаряжение!",
                inline=True
            )
            embed.set_footer(text="Не пропустите появление реликвии!")

            # Отправляем сообщение (без @everyone)
            await channel.send(embed=embed)

            # Ждем оставшиеся 10 минут
            await asyncio.sleep(600)  # 10 минут

            # Получаем канал еще раз
            channel = bot.get_channel(self.channel_id)
            if not channel:
                error_logger.error(f"Channel {self.channel_id} not found for relic timer!")
                return

            # Отправляем финальное сообщение о появлении
            final_embed = discord.Embed(
                title="✨ РЕЛИКВИЯ ПОЯВИЛАСЬ!",
                description="**Реликвия появилась!** Спешите её заполучить!",
                color=discord.Color.purple(),
                timestamp=datetime.now()
            )
            final_embed.add_field(
                name="🎯 Действуйте!",
                value="Реликвия ждёт своего героя!",
                inline=False
            )

            await channel.send(embed=final_embed)

            # Удаляем задачу из словаря после завершения
            if self.channel_id in self.tasks:
                del self.tasks[self.channel_id]

            # Очищаем данные о времени
            self.timer_start_time = None
            self.timer_duration = None

            action_logger.info(f"Relic timer completed in channel {channel.name} (ID: {self.channel_id})")

        except asyncio.CancelledError:
            # Таймер был отменен
            if self.channel_id in self.tasks:
                del self.tasks[self.channel_id]

            # Очищаем данные о времени при отмене
            self.timer_start_time = None
            self.timer_duration = None

            action_logger.info(f"Relic timer cancelled in channel ID: {self.channel_id}")
            raise

    def cancel_timer(self):
        """Отменить таймер"""
        if self.channel_id in self.tasks:
            self.tasks[self.channel_id].cancel()
            del self.tasks[self.channel_id]

            # Очищаем данные о времени
            self.timer_start_time = None
            self.timer_duration = None
            return True
        return False

    def is_active(self):
        """Проверить, активен ли таймер"""
        return self.channel_id in self.tasks

    def get_remaining_time(self):
        """Получить оставшееся время в секундах"""
        if not self.is_active() or self.timer_start_time is None or self.timer_duration is None:
            return None

        elapsed = (datetime.now() - self.timer_start_time).total_seconds()
        total_seconds = self.timer_duration * 60
        remaining = max(0, total_seconds - elapsed)
        return remaining

    def get_remaining_time_formatted(self):
        """Получить отформатированное оставшееся время"""
        remaining = self.get_remaining_time()
        if remaining is None:
            return "Неактивен"

        if remaining <= 0:
            return "0 минут"

        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)

        if hours > 0:
            return f"{hours} ч {minutes} мин {seconds} сек"
        elif minutes > 0:
            return f"{minutes} мин {seconds} сек"
        else:
            return f"{seconds} сек"


# Создаем глобальный экземпляр таймера
relic_timer = RelicTimer(RELIC_CHANNEL_ID)
bot = SlashClient()


# TODO вынести логику бд отдельно
def get_db_connection():
    conn = sqlite3.connect('./data/beacons.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Таблица маяков
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS beacons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            beacon_id TEXT NOT NULL UNIQUE,
            current_fuel REAL NOT NULL,
            current_lifetime REAL NOT NULL,
            fuel_consumption_rate REAL NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            low_status_sent BOOLEAN DEFAULT FALSE,
            message_link TEXT,
            username TEXT,
            image_url TEXT
        )
    ''')

    # Таблица участников
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created INTEGER DEFAULT 0,
            refueled INTEGER DEFAULT 0,
            repaired INTEGER DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()


init_db()


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

        current_fuel = float(beacon['current_fuel'])
        current_lifetime = float(beacon['current_lifetime'])
        fuel_consumption_rate = beacon['fuel_consumption_rate']

        # Расчет расхода топлива
        fuel_consumption_per_hour = 1 / fuel_consumption_rate
        new_fuel = current_fuel - (fuel_consumption_per_hour * hours_passed)
        new_fuel = max(0, new_fuel)

        # Расчет износа (прочности)
        # Если топлива нет (или стало 0), применяем ускоренный износ
        if new_fuel <= 0 or current_fuel <= 0:
            # Ускоренный износ: 6% в минуту = 360% в час
            # 1% в 10 секунд = 6% в минуту = 360% в час
            ACCELERATED_DECAY_RATE = 360  # 360% в час
            lifetime_decay = ACCELERATED_DECAY_RATE * hours_passed
            action_logger.debug(
                f"Accelerated decay for beacon {beacon['beacon_id']}: "
                f"no fuel, losing {ACCELERATED_DECAY_RATE:.0f}%/hour"
            )
        else:
            # Нормальный износ
            lifetime_decay = LIFETIME_DECAY_RATE * hours_passed

        new_lifetime = current_lifetime - lifetime_decay

        old_fuel = current_fuel
        old_lifetime = current_lifetime
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

            # 1. Проверка на полностью уничтоженные маяки
            if current_lifetime <= 0:
                channel = bot.get_channel(int(os.getenv("ALERT_ROLE_ID")))

                # Проверяем причину уничтожения
                if current_fuel <= 0:
                    reason = "топливо закончилось, маяк разрушился от ускоренного износа"
                else:
                    reason = "маяк полностью сгнил"

                await channel.send(
                    f"🗑️ Маяк {beacon_id} удалён: {reason}"
                )
                action_logger.info(f"Auto-deleted beacon {beacon_id}: {reason}")
                cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
                conn.commit()
                continue

            # 2. Проверка низких показателей
            fuel_percent = (current_fuel / MAX_FUEL) * 100
            lifetime_percent = current_lifetime

            # Определяем, нужно ли отправлять предупреждение
            send_warning = False
            warning_reason = []

            if fuel_percent < 20:
                warning_reason.append(f"топливо: {fuel_percent:.1f}%")
                send_warning = True
            if lifetime_percent < 20:
                warning_reason.append(f"прочность: {lifetime_percent:.1f}%")
                send_warning = True

            # Дополнительное предупреждение о критическом топливе (ускоренный износ скоро начнется)
            if fuel_percent < 5 and lifetime_percent > 0:
                warning_reason.append(f"⚠️ ТОПЛИВО НА ИСХОДЕ! Скоро начнется ускоренный износ!")
                send_warning = True

            if send_warning and not low_status_sent:
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

                channel = bot.get_channel(int(os.getenv("ALERT_ROLE_ID")))

                # Создаем embed для восстановления
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


# ============== ФУНКЦИИ ДЛЯ АВТОДОПОЛНЕНИЯ КОМАНДЫ RELIC ==============

async def get_minute_options(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[int]]:
    """Возвращает список вариантов минут для автодополнения"""
    # Стандартные варианты
    options = [
        (90, "90 минут (1 час 30 минут)"),
        (60, "60 минут (1 час)"),
        (120, "120 минут (2 часа)"),
        (30, "30 минут"),
        (45, "45 минут"),
        (15, "15 минут"),
    ]

    choices = []
    for value, name in options:
        if not current or current.isdigit() and str(value).startswith(current):
            choices.append(app_commands.Choice(name=name, value=value))

    return choices[:25]

def get_priority_text(rate: float) -> tuple:
    """Возвращает эмодзи и текст приоритета по значению rate"""
    if rate == 1:
        return "🔴", "Высокий"
    elif rate == 1.5:
        return "🟡", "Средний"
    else:
        return "🟢", "Низкий"


def get_progress_bar(value: float, max_value: float, bar_length: int = 10) -> str:
    """Создает полоску прогресса"""
    percent = (value / max_value) * 100
    filled = int(percent / (100 / bar_length))
    return "█" * filled + "░" * (bar_length - filled)


def get_status_emoji(percent: float, threshold_warning: int = 20, threshold_critical: int = 5) -> str:
    """Возвращает эмодзи статуса в зависимости от процента"""
    if percent <= threshold_critical:
        return "💀"
    elif percent <= threshold_warning:
        return "⚠️"
    return "✅"


def create_embed(title: str, description: str, color: discord.Color,
                 fields: List[tuple] = None, footer: str = None,
                 timestamp: bool = True, link: str = None) -> discord.Embed:
    """Создает стандартизированный embed"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now() if timestamp else None
    )

    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    if link:
        embed.add_field(name="", value=f"🔗 [Перейти]({link})", inline=False)

    if footer:
        embed.add_field(name="", value=footer, inline=False)

    return embed


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
        cursor.execute(
            'SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate FROM beacons ORDER BY beacon_id')
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


# ============== НОВЫЙ КЛАСС ДЛЯ ДОБАВЛЕНИЯ МАЯКА С ИЗОБРАЖЕНИЕМ ==============

class AddBeaconWithImageView(View):
    """View для добавления маяка с изображением"""

    def __init__(self, interaction: discord.Interaction, beacon_data: dict):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.beacon_data = beacon_data
        self.image_attachment: Optional[discord.Attachment] = None
        self.image_url: Optional[str] = None

        # Добавляем кнопку для подтверждения
        self.confirm_button = Button(
            label="✅ Подтвердить",
            style=discord.ButtonStyle.success,
            emoji="✅",
            disabled=True  # Изначально отключена
        )
        self.confirm_button.callback = self.confirm_callback
        self.add_item(self.confirm_button)

        # Кнопка отмены
        self.cancel_button = Button(
            label="❌ Отмена",
            style=discord.ButtonStyle.danger,
            emoji="❌"
        )
        self.cancel_button.callback = self.cancel_callback
        self.add_item(self.cancel_button)

    @discord.ui.button(label="📷 Добавить изображение", style=discord.ButtonStyle.primary, emoji="🖼️")
    async def add_image_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка для добавления изображения"""
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "❌ Вы не можете управлять этим диалогом!",
                ephemeral=True
            )
            return

        # Создаем модальное окно для вставки URL или загрузки изображения
        class ImageModal(Modal, title="🖼️ Добавление изображения"):
            image_url = TextInput(
                label="Ссылка на изображение (опционально)",
                placeholder="Вставьте URL изображения или нажмите кнопку 'Загрузить файл'",
                required=False,
                max_length=500
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                if modal_interaction.user.id != interaction.user.id:
                    await modal_interaction.response.send_message(
                        "❌ Вы не можете управлять этим диалогом!",
                        ephemeral=True
                    )
                    return

                if self.image_url.value:
                    # Проверяем, что это валидный URL изображения
                    if self.image_url.value.startswith(('http://', 'https://')):
                        # Обновляем данные
                        view = modal_interaction.message.view
                        if view and isinstance(view, AddBeaconWithImageView):
                            view.image_url = self.image_url.value
                            view.confirm_button.disabled = False

                            # Обновляем embed с изображением
                            embed = modal_interaction.message.embeds[
                                0] if modal_interaction.message.embeds else discord.Embed(
                                title="📝 Добавление маяка",
                                color=discord.Color.blue()
                            )
                            embed.set_image(url=self.image_url.value)

                            await modal_interaction.response.edit_message(
                                embed=embed,
                                view=view
                            )
                            await modal_interaction.followup.send(
                                "✅ Изображение успешно добавлено!",
                                ephemeral=True
                            )
                    else:
                        await modal_interaction.response.send_message(
                            "❌ Невалидный URL изображения!",
                            ephemeral=True
                        )
                else:
                    await modal_interaction.response.send_message(
                        "❌ Вы не указали ссылку на изображение!",
                        ephemeral=True
                    )

        # Отправляем модальное окно
        await interaction.response.send_modal(ImageModal())

    @discord.ui.button(label="📤 Загрузить файл", style=discord.ButtonStyle.secondary, emoji="📎")
    async def upload_file_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка для загрузки файла"""
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "❌ Вы не можете управлять этим диалогом!",
                ephemeral=True
            )
            return

        # Проверяем наличие вложений
        if not interaction.message.attachments:
            await interaction.response.send_message(
                "❌ Прикрепите файл к сообщению!",
                ephemeral=True
            )
            return

        # Проверяем, что это изображение
        for attachment in interaction.message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                self.image_attachment = attachment
                self.image_url = attachment.url
                self.confirm_button.disabled = False

                # Обновляем embed с изображением
                embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(
                    title="📝 Добавление маяка",
                    color=discord.Color.blue()
                )
                embed.set_image(url=attachment.url)

                await interaction.response.edit_message(
                    embed=embed,
                    view=self
                )
                await interaction.followup.send(
                    "✅ Изображение успешно загружено!",
                    ephemeral=True
                )
                return

        await interaction.response.send_message(
            "❌ Прикрепленный файл не является изображением!",
            ephemeral=True
        )

    async def confirm_callback(self, interaction: discord.Interaction):
        """Подтверждение создания маяка"""
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "❌ Вы не можете управлять этим диалогом!",
                ephemeral=True
            )
            return

        # Создаем маяк
        await self.create_beacon(interaction)

    async def cancel_callback(self, interaction: discord.Interaction):
        """Отмена создания маяка"""
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "❌ Вы не можете управлять этим диалогом!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="❌ Отмена",
            description="Добавление маяка отменено.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def create_beacon(self, interaction: discord.Interaction):
        """Создание маяка в базе данных"""
        user_info = get_user_info(interaction)
        user_id = str(interaction.user.id)
        username = interaction.user.name

        try:
            beacon_id = self.beacon_data['beacon_id']
            priority = self.beacon_data['priority']
            current_fuel = self.beacon_data['fuel']
            current_lifetime = self.beacon_data['lifetime']

            if priority == 1:
                fuel_consumption_rate = 1
                priority_text = "🔴 Высокий"
            elif priority == 2:
                fuel_consumption_rate = 1.5
                priority_text = "🟡 Средний"
            else:
                fuel_consumption_rate = 2
                priority_text = "🟢 Низкий"

            # Создаем embed
            embed = discord.Embed(
                title="✅ Добавлен маяк",
                description=f"**{beacon_id}**",
                color=discord.Color.green()
            )
            embed.add_field(name="🔋 Топливо", value=f"{current_fuel:.1f}/{MAX_FUEL}")
            embed.add_field(name="🔄 Прочность", value=f"{current_lifetime:.1f}%")
            embed.add_field(name="📊 Приоритет", value=priority_text)
            embed.add_field(name="", value=f"Добавил: {interaction.user.mention}", inline=False)

            # Добавляем изображение, если есть
            if self.image_url:
                embed.set_image(url=self.image_url)

            # Отправляем сообщение в канал
            sent_message = await interaction.channel.send(embed=embed)

            # Сохраняем ссылку на сообщение
            message_link = sent_message.jump_url

            # Сохраняем в базу данных
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO beacons 
                (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate, last_updated, low_status_sent, message_link, username, image_url) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate,
                 datetime.now().isoformat(), False, message_link, username, self.image_url)
            )
            conn.commit()

            # Обновляем статистику пользователя
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()

            if user:
                cursor.execute('''
                    UPDATE users 
                    SET created = created + 1, username = ?
                    WHERE user_id = ?
                ''', (username, user_id))
            else:
                cursor.execute('''
                    INSERT INTO users (user_id, username, created, refueled, repaired)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, 1, 0, 0))

            conn.commit()
            conn.close()

            # Логируем
            action_logger.info(
                f"{user_info} added beacon {beacon_id} via image form | "
                f"Fuel: {current_fuel}/{MAX_FUEL}, Lifetime: {current_lifetime}%, Priority: {priority}, Image: {bool(self.image_url)}"
            )

            # Отправляем подтверждение
            await interaction.response.edit_message(
                content=f"✅ Маяк {beacon_id} успешно добавлен!",
                embed=None,
                view=None
            )

        except sqlite3.IntegrityError:
            await interaction.response.edit_message(
                content=f"❌ Маяк {beacon_id} уже существует!",
                embed=None,
                view=None
            )
        except Exception as e:
            error_msg = f"Ошибка при создании маяка: {str(e)}"
            error_logger.error(f"{user_info} {error_msg}", exc_info=True)
            await interaction.response.edit_message(
                content=f"❌ Ошибка: {str(e)}",
                embed=None,
                view=None
            )


# ============== КОМАНДА /add С ПОДСКАЗКАМИ И ОБЯЗАТЕЛЬНЫМ ИЗОБРАЖЕНИЕМ ==============

@bot.tree.command(name="add", description="Добавить новый маяк")
@app_commands.describe(
    beacon_id="ID маяка (например: NG-01)",
    priority="Приоритет маяка (1 - высокий, 2 - средний, 3 - низкий)",
    fuel="Количество топлива (0-30, оставьте пустым для полного бака)",
    lifetime="Прочность в процентах (0-100, оставьте пустым для полной прочности)",
    image="Изображение маяка (обязательно! Перетащите или нажмите для загрузки)"
)
@app_commands.choices(
    priority=[
        app_commands.Choice(name="🔴 1 - Высокий (быстрый расход топлива)", value=1),
        app_commands.Choice(name="🟡 2 - Средний (стандартный расход)", value=2),
        app_commands.Choice(name="🟢 3 - Низкий (экономный расход)", value=3),
    ]
)
async def add(
        interaction: discord.Interaction,
        beacon_id: str,
        priority: app_commands.Choice[int],
        image: discord.Attachment,  # Обязательный параметр
        fuel: Optional[str] = None,
        lifetime: Optional[str] = None,
):
    """
    Добавить новый маяк с обязательным изображением.
    При вызове команды автоматически появляется окно для загрузки файла.
    Изображение отображается в сообщении, но не сохраняется в БД.
    """
    # Проверяем, что ID не пустой
    if not beacon_id or len(beacon_id) > 20:
        await interaction.response.send_message(
            "❌ ID маяка должен быть от 1 до 20 символов!",
            ephemeral=True
        )
        return

    # Проверяем изображение
    if not image:
        await interaction.response.send_message(
            "❌ Изображение обязательно для добавления маяка!",
            ephemeral=True
        )
        return

    # Проверяем, что это изображение
    if not image.content_type or not image.content_type.startswith('image/'):
        await interaction.response.send_message(
            "❌ Загруженный файл должен быть изображением!",
            ephemeral=True
        )
        return

    # Проверяем размер (максимум 25MB)
    if image.size > 25 * 1024 * 1024:
        await interaction.response.send_message(
            "❌ Размер изображения не должен превышать 25MB!",
            ephemeral=True
        )
        return

    # Обработка топлива
    try:
        if fuel and fuel.strip():
            current_fuel = float(fuel)
            if current_fuel < 0 or current_fuel > MAX_FUEL:
                await interaction.response.send_message(
                    f"❌ Топливо должно быть от 0 до {MAX_FUEL}!",
                    ephemeral=True
                )
                return
        else:
            current_fuel = MAX_FUEL
    except ValueError:
        await interaction.response.send_message(
            "❌ Топливо должно быть числом!",
            ephemeral=True
        )
        return

    # Обработка прочности
    try:
        if lifetime and lifetime.strip():
            current_lifetime = float(lifetime)
            if current_lifetime < 0 or current_lifetime > MAX_LIFETIME:
                await interaction.response.send_message(
                    f"❌ Прочность должна быть от 0 до {MAX_LIFETIME}!",
                    ephemeral=True
                )
                return
        else:
            current_lifetime = MAX_LIFETIME
    except ValueError:
        await interaction.response.send_message(
            "❌ Прочность должна быть числом!",
            ephemeral=True
        )
        return

    # Проверяем, существует ли уже такой маяк
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT beacon_id FROM beacons WHERE beacon_id = ?', (beacon_id,))
    existing = cursor.fetchone()
    conn.close()

    if existing:
        await interaction.response.send_message(
            f"❌ Маяк {beacon_id} уже существует!",
            ephemeral=True
        )
        return

    # Создаем маяк
    user_info = get_user_info(interaction)
    user_id = str(interaction.user.id)
    username = interaction.user.name

    try:
        if priority.value == 1:
            fuel_consumption_rate = 1
            priority_text = "🔴 Высокий"
        elif priority.value == 2:
            fuel_consumption_rate = 1.5
            priority_text = "🟡 Средний"
        else:
            fuel_consumption_rate = 2
            priority_text = "🟢 Низкий"

        # Создаем embed
        embed = discord.Embed(
            title="✅ Добавлен маяк",
            description=f"**{beacon_id}**",
            color=discord.Color.green()
        )
        embed.add_field(name="🔋 Топливо", value=f"{current_fuel:.1f}/{MAX_FUEL}")
        embed.add_field(name="🔄 Прочность", value=f"{current_lifetime:.1f}%")
        embed.add_field(name="📊 Приоритет", value=priority_text)
        embed.add_field(name="", value=f"Добавил: {interaction.user.mention}", inline=False)

        # Добавляем изображение (оно обязательно, поэтому всегда есть)
        embed.set_image(url=image.url)

        # Отправляем сообщение в канал
        sent_message = await interaction.channel.send(embed=embed)

        # Сохраняем ссылку на сообщение
        message_link = sent_message.jump_url

        # Сохраняем в базу данных (БЕЗ image_url)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO beacons 
            (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate, last_updated, low_status_sent, message_link, username) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (beacon_id, current_fuel, current_lifetime, fuel_consumption_rate,
             datetime.now().isoformat(), False, message_link, username)
        )
        conn.commit()

        # Обновляем статистику пользователя
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()

        if user:
            cursor.execute('''
                UPDATE users 
                SET created = created + 1, username = ?
                WHERE user_id = ?
            ''', (username, user_id))
        else:
            cursor.execute('''
                INSERT INTO users (user_id, username, created, refueled, repaired)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, 1, 0, 0))

        conn.commit()
        conn.close()

        # Логируем (без сохранения URL изображения)
        action_logger.info(
            f"{user_info} added beacon {beacon_id} | "
            f"Fuel: {current_fuel}/{MAX_FUEL}, Lifetime: {current_lifetime}%, Priority: {priority.value}"
        )

        # Отправляем подтверждение
        await interaction.response.send_message(
            f"✅ Маяк {beacon_id} успешно добавлен с изображением!",
            ephemeral=True
        )

    except sqlite3.IntegrityError:
        await interaction.response.send_message(
            f"❌ Маяк {beacon_id} уже существует!",
            ephemeral=True
        )
    except Exception as e:
        error_msg = f"Ошибка при создании маяка: {str(e)}"
        error_logger.error(f"{user_info} {error_msg}", exc_info=True)
        await interaction.response.send_message(
            f"❌ Ошибка: {str(e)}",
            ephemeral=True
        )


# ============== ОСТАЛЬНЫЕ КОМАНДЫ (БЕЗ ИЗМЕНЕНИЙ) ==============

# ... (здесь должны быть остальные команды: menu, refuel, status, edit, delete, clear, ping)
# Для полноты кода я добавлю их в следующей части

# ============== КЛАССЫ ДЛЯ МОДАЛЬНЫХ ОКОН (ОСТАВЛЯЕМ ДЛЯ СОВМЕСТИМОСТИ) ==============

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
        user_id = str(interaction.user.id)
        username = interaction.user.name

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT current_fuel, current_lifetime, message_link FROM beacons WHERE beacon_id = ?',
                           (self.beacon_id_input.value,))
            result = cursor.fetchone()

            if not result:
                await interaction.response.send_message(
                    f"❌ Маяк {self.beacon_id_input.value} не найден!",
                    ephemeral=True
                )
                return

            current = float(result['current_fuel'])
            current_lifetime = float(result['current_lifetime'])
            new_fuel = min(current + amount, MAX_FUEL)
            message_link = result['message_link']

            added_amount = new_fuel - current

            fuel_percent = (new_fuel / MAX_FUEL) * 100
            reset_status = (fuel_percent >= 20 and current_lifetime >= 20)

            cursor.execute('''
                UPDATE beacons 
                SET current_fuel = ?, 
                    last_updated = ?,
                    low_status_sent = ?
                WHERE beacon_id = ?
            ''', (new_fuel, datetime.now().isoformat(), not reset_status, self.beacon_id_input.value))

            conn.commit()

            if added_amount >= (MAX_FUEL / 2):
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                user = cursor.fetchone()

                if user:
                    cursor.execute('''
                        UPDATE users 
                        SET refueled = refueled + 1, username = ?
                        WHERE user_id = ?
                    ''', (username, user_id))
                else:
                    cursor.execute('''
                        INSERT INTO users (user_id, username, created, refueled, repaired)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (user_id, username, 0, 1, 0))

                conn.commit()
                action_logger.info(
                    f"User {username} earned refuel point for beacon {self.beacon_id_input.value}: "
                    f"added {added_amount:.1f} fuel (≥15)"
                )

            action_logger.info(
                f"{get_user_info(interaction)} modal refueled beacon {self.beacon_id_input.value} | "
                f"Added: {amount:.1f}, Real added: {added_amount:.1f}, "
                f"Old: {current:.1f}, New: {new_fuel:.1f}/{MAX_FUEL}"
            )

            embed = discord.Embed(
                title="⛽ Заправлен маяк",
                description=f"**{self.beacon_id_input.value}**",
                color=discord.Color.blue()
            )
            embed.add_field(name="Новое топливо", value=f"{new_fuel:.1f}/{MAX_FUEL}")
            embed.add_field(name="Добавлено", value=f"{added_amount:.1f}")

            if message_link:
                embed.add_field(name="", value=f"🔗 [Перейти]({message_link})", inline=False)

            embed.add_field(name="", value=f"Заправил: {interaction.user.mention}", inline=False)

            await interaction.response.send_message(
                f"✅ Заправка маяка {self.beacon_id_input.value} выполнена!",
                ephemeral=True
            )

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

        user_id = str(interaction.user.id)
        username = interaction.user.name

        earned_refuel = False
        earned_repair = False
        fuel_added = 0
        lifetime_added = 0

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

        old_fuel = float(current_beacon['current_fuel'])
        old_lifetime = float(current_beacon['current_lifetime'])
        old_rate = current_beacon['fuel_consumption_rate']
        message_link = current_beacon['message_link']

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

                if new_fuel > old_fuel:
                    fuel_added = new_fuel - old_fuel
                    if fuel_added >= (MAX_FUEL / 2):
                        earned_refuel = True

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

                if new_lifetime > old_lifetime:
                    lifetime_added = new_lifetime - old_lifetime
                    if lifetime_added >= (MAX_LIFETIME / 2):
                        earned_repair = True

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
                if earned_refuel:
                    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                    user = cursor.fetchone()

                    if user:
                        cursor.execute('''
                            UPDATE users 
                            SET refueled = refueled + 1, username = ?
                            WHERE user_id = ?
                        ''', (username, user_id))
                    else:
                        cursor.execute('''
                            INSERT INTO users (user_id, username, created, refueled, repaired)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (user_id, username, 0, 1, 0))

                    conn.commit()
                    action_logger.info(
                        f"User {username} earned refuel point via edit for beacon {self.beacon_id_input.value}: "
                        f"added {fuel_added:.1f} fuel (≥15)"
                    )

                if earned_repair:
                    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                    user = cursor.fetchone()

                    if user:
                        cursor.execute('''
                            UPDATE users 
                            SET repaired = repaired + 1, username = ?
                            WHERE user_id = ?
                        ''', (username, user_id))
                    else:
                        cursor.execute('''
                            INSERT INTO users (user_id, username, created, refueled, repaired)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (user_id, username, 0, 0, 1))

                    conn.commit()
                    action_logger.info(
                        f"User {username} earned repair point via edit for beacon {self.beacon_id_input.value}: "
                        f"added {lifetime_added:.1f}% lifetime (≥50%)"
                    )

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

                await interaction.response.send_message(
                    f"✅ Данные маяка {self.beacon_id_input.value} успешно обновлены!",
                    ephemeral=True
                )

                await interaction.channel.send(embed=embed)

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

            cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
            conn.commit()

            embed = discord.Embed(
                title="🗑️ Маяк удалён",
                description=f"**{beacon_id}**",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )

            embed.add_field(name="", value=f"Удалил: {interaction.user.mention}", inline=False)

            action_logger.info(
                f"{get_user_info(interaction)} modal deleted beacon {beacon_id} | "
                f"Fuel: {current_fuel}/{MAX_FUEL}, Lifetime: {current_lifetime}%, Priority: {priority_text}"
            )

            await interaction.response.send_message(
                f"✅ Маяк {beacon_id} успешно удалён!",
                ephemeral=True
            )

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

            if action_type == "status":
                options.append(
                    discord.SelectOption(
                        label="📊 Показать все маяки",
                        value="all",
                        description="Показать статус всех маяков",
                        emoji="📋"
                    )
                )

            for beacon in beacons[:24]:
                beacon_id = beacon['beacon_id']
                fuel = beacon['current_fuel']
                lifetime = beacon['current_lifetime']
                rate = beacon['fuel_consumption_rate']

                if rate == 1:
                    emoji = "🔴"
                elif rate == 1.5:
                    emoji = "🟡"
                else:
                    emoji = "🟢"

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

        if self.action_type == "status":
            if beacon_id == "all":
                await show_all_beacons_status(interaction)
            else:
                await show_beacon_status(interaction, beacon_id)
            return

        if self.action_type == "refuel":
            await interaction.response.send_modal(RefuelModal(beacon_id))
        elif self.action_type == "edit":
            await interaction.response.send_modal(EditBeaconModal(beacon_id))
        elif self.action_type == "delete":
            await interaction.response.send_modal(DeleteBeaconModal(beacon_id))

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

            status_emoji = ""
            if beacon['current_lifetime'] <= 20 or fuel_percent <= 20:
                status_emoji = "⚠️ "
            elif beacon['current_lifetime'] <= 5 or fuel_percent <= 5:
                status_emoji = "💀 "

            field_value = f"🔋 {fuel_bar} {beacon['current_fuel']:.1f}/{MAX_FUEL}\n🔄 {lifetime_bar} {beacon['current_lifetime']:.1f}%"

            if beacon['message_link']:
                field_value += f"\n[Перейти]({beacon['message_link']})"

            embed.add_field(
                name=f"{status_emoji}{priority_text} {beacon['beacon_id']}",
                value=field_value,
                inline=False
            )

        embed.set_footer(text="🔴 Высокий | 🟡 Средний | 🟢 Низкий | ⚠️ Требует внимания")

        await interaction.response.send_message(
            "✅ Статус всех маяков отправлен в чат",
            ephemeral=True
        )

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
        super().__init__(timeout=120)

    @discord.ui.button(label="Добавить маяк", style=discord.ButtonStyle.green, emoji="➕", row=0)
    async def add_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка добавления маяка (открывает форму с подсказками)"""
        # Открываем форму добавления через /add
        await interaction.response.send_message(
            "Используйте команду `/add` для добавления маяка:\n",
            ephemeral=True
        )

    @discord.ui.button(label="Заправить", style=discord.ButtonStyle.primary, emoji="⛽", row=0)
    async def refuel_button(self, interaction: discord.Interaction, button: Button):
        """Кнопка заправки маяка с выбором из списка"""
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

                    cursor.execute(
                        'SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate FROM beacons')
                    beacons = cursor.fetchall()
                    beacon_list = [b['beacon_id'] for b in beacons]
                    count_before = len(beacon_list)

                    cursor.execute('DELETE FROM beacons')
                    conn.commit()

                    if count_before > 0:
                        action_logger.info(
                            f"{get_user_info(btn_interaction)} cleared ALL beacons via menu button | "
                            f"Deleted: {count_before} beacons: {', '.join(beacon_list)}"
                        )

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

                    await btn_interaction.channel.send(embed=embed)

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
                for item in self.children:
                    item.disabled = True
                try:
                    await self.original_interaction.edit_original_response(
                        content="⌛ Время подтверждения истекло. Очистка отменена.",
                        embed=None,
                        view=self
                    )
                except:
                    pass

        embed = discord.Embed(
            title="⚠️ Подтверждение действия",
            description="Вы уверены, что хотите удалить **ВСЕ** маяки?\nЭто действие нельзя отменить!",
            color=discord.Color.yellow()
        )
        embed.set_footer(text="У вас есть 30 секунд на подтверждение")

        view = ConfirmClearView(interaction.user, interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ============== ОСТАЛЬНЫЕ КОМАНДЫ ==============

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


@bot.tree.command(name="refuel", description="Пополнить топливо маяка")
async def refuel(interaction: discord.Interaction):
    """Пополнить топливо маяка через интерфейс"""
    user_info = get_user_info(interaction)

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

                cursor.execute('SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate FROM beacons')
                beacons = cursor.fetchall()
                beacon_list = [b['beacon_id'] for b in beacons]
                count_before = len(beacon_list)

                cursor.execute('DELETE FROM beacons')
                conn.commit()

                if count_before > 0:
                    action_logger.info(
                        f"{get_user_info(button_interaction)} cleared ALL beacons | "
                        f"Deleted: {count_before} beacons: {', '.join(beacon_list)}"
                    )

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

                await button_interaction.channel.send(embed=embed)

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

    embed = discord.Embed(
        title="⚠️ Подтверждение действия",
        description="Вы уверены, что хотите удалить **ВСЕ** маяки?\nЭто действие нельзя отменить!",
        color=discord.Color.yellow()
    )
    embed.set_footer(text="У вас есть 30 секунд на подтверждение")

    view = ConfirmView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
    """Бот жив?"""
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)


# ============== КОМАНДА RELIC ==============

@bot.tree.command(name="relic", description="Запустить таймер до появления реликвии (по умолчанию 90 минут)")
@app_commands.describe(
    minutes="Время до появления реликвии в минутах (по умолчанию 90)"
)
@app_commands.autocomplete(minutes=get_minute_options)
async def relic(
        interaction: discord.Interaction,
        minutes: Optional[int] = None
):
    """
    Запустить таймер до появления реликвии.
    По умолчанию: 90 минут (1 час 30 минут).
    Можно указать другое время в минутах.
    """
    user_info = get_user_info(interaction)

    # Проверяем, настроен ли канал для реликвий
    if RELIC_CHANNEL_ID == 0:
        await interaction.response.send_message(
            "❌ Канал для реликвий не настроен! Добавьте RELIC_CHANNEL в .env файл.",
            ephemeral=True
        )
        error_logger.error(f"{user_info} tried to use /relic but RELIC_CHANNEL is not configured")
        return

    # Получаем канал
    relic_channel = bot.get_channel(RELIC_CHANNEL_ID)
    if not relic_channel:
        await interaction.response.send_message(
            f"❌ Канал с ID {RELIC_CHANNEL_ID} не найден! Проверьте настройки.",
            ephemeral=True
        )
        error_logger.error(f"{user_info} tried to use /relic but channel {RELIC_CHANNEL_ID} not found")
        return

    # Устанавливаем время по умолчанию
    if minutes is None:
        minutes = 90
    elif minutes < 1:
        await interaction.response.send_message(
            "❌ Время должно быть больше 0 минут!",
            ephemeral=True
        )
        return
    elif minutes > 1440:  # Максимум 24 часа
        await interaction.response.send_message(
            "❌ Время не должно превышать 1440 минут (24 часа)!",
            ephemeral=True
        )
        return

    # Проверяем, есть ли уже активный таймер
    if relic_timer.is_active():
        # Создаем кнопки для управления
        class TimerManageView(View):
            def __init__(self):
                super().__init__(timeout=30)

            @discord.ui.button(label="Отменить таймер", style=discord.ButtonStyle.danger, emoji="⏹️")
            async def cancel_timer_button(self, btn_interaction: discord.Interaction, button: Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message(
                        "❌ Вы не можете управлять этим таймером!",
                        ephemeral=True
                    )
                    return

                if relic_timer.cancel_timer():
                    embed = discord.Embed(
                        title="⏹️ Таймер отменен",
                        description="Таймер появления реликвии был отменен.",
                        color=discord.Color.red(),
                        timestamp=datetime.now()
                    )
                    await btn_interaction.response.edit_message(
                        embed=embed,
                        view=None
                    )
                    action_logger.info(
                        f"{get_user_info(btn_interaction)} cancelled relic timer")
                else:
                    await btn_interaction.response.edit_message(
                        content="❌ Таймер не найден или уже завершен.",
                        view=None
                    )

            @discord.ui.button(label="Перезапустить", style=discord.ButtonStyle.primary, emoji="🔄")
            async def restart_timer_button(self, btn_interaction: discord.Interaction, button: Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message(
                        "❌ Вы не можете управлять этим таймером!",
                        ephemeral=True
                    )
                    return

                # Отменяем старый таймер
                relic_timer.cancel_timer()

                # Запускаем новый
                await relic_timer.start_timer(bot, minutes)

                hours = minutes // 60
                mins = minutes % 60
                time_str = f"{hours} ч {mins} мин" if hours > 0 else f"{mins} мин"

                embed = discord.Embed(
                    title="🔄 Таймер перезапущен",
                    description=f"Таймер появления реликвии перезапущен на **{time_str}**",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                embed.add_field(
                    name="⏰ Время до появления",
                    value=f"**{time_str}**",
                    inline=True
                )
                embed.add_field(
                    name="📢 Уведомление",
                    value="За 10 минут до появления будет отправлено предупреждение",
                    inline=False
                )
                embed.add_field(
                    name="📌 Канал",
                    value=f"{relic_channel.mention}",
                    inline=False
                )

                await btn_interaction.response.edit_message(
                    embed=embed,
                    view=None
                )

                action_logger.info(
                    f"{get_user_info(btn_interaction)} restarted relic timer for {minutes} minutes")

        # Если таймер уже есть, предлагаем управление
        embed = discord.Embed(
            title="⏳ Таймер уже запущен",
            description=f"В канале {relic_channel.mention} уже запущен таймер появления реликвии.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="🔄 Что делать?",
            value="Вы можете отменить текущий таймер или перезапустить его с новым временем.",
            inline=False
        )

        view = TimerManageView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    # Запускаем новый таймер в указанном канале
    await relic_timer.start_timer(bot, minutes)

    hours = minutes // 60
    mins = minutes % 60
    time_str = f"{hours} ч {mins} мин" if hours > 0 else f"{mins} мин"

    # Создаем embed с информацией (эфемерное сообщение)
    embed = discord.Embed(
        title="⏳ Таймер реликвии запущен",
        description=f"Реликвия появится через **{time_str}**",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    embed.add_field(
        name="📢 Уведомление",
        value="За 10 минут до появления будет отправлено предупреждение",
        inline=False
    )
    embed.add_field(
        name="⏰ Время появления",
        value=f"~{datetime.now().strftime('%H:%M')} + {time_str}",
        inline=True
    )
    embed.add_field(
        name="📌 Канал",
        value=f"{relic_channel.mention}",
        inline=True
    )
    embed.add_field(
        name="📊 Статус",
        value="🟢 Активен",
        inline=True
    )
    embed.set_footer(text=f"Запустил: {interaction.user.name}")

    # Отправляем эфемерное сообщение пользователю
    await interaction.response.send_message(embed=embed, ephemeral=True)

    # Логируем
    action_logger.info(
        f"{user_info} started relic timer in channel {relic_channel.name} (ID: {relic_channel.id}) for {minutes} minutes"
    )

@bot.tree.command(name="relic_cancel", description="Отменить запущенный таймер реликвии")
async def relic_cancel(interaction: discord.Interaction):
    """Отменить таймер реликвии"""
    user_info = get_user_info(interaction)

    # Проверяем, настроен ли канал для реликвий
    if RELIC_CHANNEL_ID == 0:
        await interaction.response.send_message(
            "❌ Канал для реликвий не настроен!",
            ephemeral=True
        )
        return

    if relic_timer.cancel_timer():
        embed = discord.Embed(
            title="⏹️ Таймер отменен",
            description="Таймер появления реликвии был успешно отменен.",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        action_logger.info(f"{user_info} cancelled relic timer")
    else:
        await interaction.response.send_message(
            "❌ Нет активного таймера реликвии.",
            ephemeral=True
        )


@bot.tree.command(name="relic_status", description="Показать статус таймера реликвии")
async def relic_status(interaction: discord.Interaction):
    """Показать статус таймера реликвии"""

    # Проверяем, настроен ли канал для реликвий
    if RELIC_CHANNEL_ID == 0:
        await interaction.response.send_message(
            "❌ Канал для реликвий не настроен!",
            ephemeral=True
        )
        return

    relic_channel = bot.get_channel(RELIC_CHANNEL_ID)
    if not relic_channel:
        await interaction.response.send_message(
            f"❌ Канал с ID {RELIC_CHANNEL_ID} не найден!",
            ephemeral=True
        )
        return

    if relic_timer.is_active():
        # Получаем оставшееся время
        remaining_time = relic_timer.get_remaining_time_formatted()

        embed = discord.Embed(
            title="⏳ Таймер реликвии активен",
            description=f"В канале {relic_channel.mention} запущен таймер появления реликвии.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )

        # Добавляем информацию об оставшемся времени
        embed.add_field(
            name="⏱️ Оставшееся время",
            value=f"**{remaining_time}**",
            inline=False
        )

        embed.add_field(
            name="📢 Уведомление",
            value="За 10 минут до появления будет отправлено предупреждение",
            inline=True
        )
        embed.add_field(
            name="📌 Канал",
            value=f"{relic_channel.mention}",
            inline=True
        )

        # Добавляем примерное время появления со знаком ~
        if relic_timer.timer_start_time and relic_timer.timer_duration:
            appear_time = relic_timer.timer_start_time + timedelta(minutes=relic_timer.timer_duration)
            embed.add_field(
                name="⏰ Примерное время появления",
                value=f"~{appear_time.strftime('%H:%M:%S')}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title="❌ Таймер не активен",
            description="Нет запущенного таймера реликвии.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="💡 Запустить таймер",
            value="Используйте команду `/relic` для запуска таймера",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
bot.run(os.getenv("TOKEN"))