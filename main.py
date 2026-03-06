import os
import sqlite3
from datetime import datetime

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()
# Константы
MAX_FUEL = 30  # Максимальное значение топлива (единицы)
MAX_LIFETIME = 100  # Максимальный срок действия (проценты)
FUEL_HIGH_CONSUMPTION_RATE = 1 / 1  # 1 единица топлива расходуется за 1 часа при обнаружении противника или вражеских строений
FUEL_MEDIUM_CONSUMPTION_RATE = 1 / 1.5  # Ориентировочный расход топлива за 1 час, при редком обнаружении
FUEL_LOW_CONSUMPTION_RATE = 1 / 1.9  # 1 единица топлива расходуется за 1 часа если маяк в тылу
LIFETIME_DECAY_RATE = 100 / 48  # 100% расходуется за 48 часа (в процентах в час)
# FUEL_CONSUMPTION_RATE = 300 / 1  # 1 единица топлива расходуется за 2 часа
# LIFETIME_DECAY_RATE = 100 / 1  # 100% расходуется за 48 часа (в процентах в час)


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


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

        new_fuel = float(beacon['current_fuel']) - float(beacon['fuel_consumption_rate'] * hours_passed)
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


@bot.command()
async def add(ctx, beacon_id: str, priority: int = 2, current_fuel: float = None, current_lifetime: float = None):
    """Добавить новый маяк
    Пример: !add BCN-001 30 100 2
    Приоритет: 1 - высокий, 2 - средний, 3 - низкий (по умолчанию 2)
    """
    # Проверка приоритета
    if priority not in [1, 2, 3]:
        await ctx.send("Ошибка: приоритет должен быть 1, 2 или 3\n"
                       "1 - высокий\n"
                       "2 - средний\n"
                       "3 - низкий")
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
        await ctx.send(f"Ошибка: значения не могут превышать {MAX_FUEL} для топлива и {MAX_LIFETIME}% для срока")
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

        await ctx.send(f"Маяк {beacon_id} успешно добавлен\n"
                       f"🔋 Топливо: {current_fuel}\n"
                       f"🔄 Прочность: {current_lifetime}%\n"
                       f"📊 Приоритет: {priority_text}")
    except sqlite3.IntegrityError:
        await ctx.send(f"Маяк {beacon_id} уже существует!")
    except Exception as e:
        await ctx.send(f"Ошибка: {str(e)}")
    finally:
        conn.close()


@bot.command()
async def refuel(ctx, beacon_id: str, amount: float = None):
    """Пополнить топливо маяка по ID"""
    if amount is None:
        amount = MAX_FUEL

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT current_fuel FROM beacons WHERE beacon_id = ?', (beacon_id,))
        result = cursor.fetchone()

        if not result:
            await ctx.send(f"Маяк {beacon_id} не найден!")
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
        await ctx.send(f"Топливо маяка {beacon_id} пополнено до {new_fuel}/{MAX_FUEL}")
    except Exception as e:
        await ctx.send(f"Ошибка: {str(e)}")
    finally:
        conn.close()


@bot.command()
async def status(ctx, beacon_id: str = None):
    """Показать статус маяка по ID или всех маяков"""
    global priority_text
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if beacon_id:
            cursor.execute('SELECT * FROM beacons WHERE beacon_id = ?', (beacon_id,))
            beacon = cursor.fetchone()

            if not beacon:
                await ctx.send(f"Маяк {beacon_id} не найден или уже сгнил!")
                return

            hours_remaining_fuel = beacon['current_fuel']* beacon['fuel_consumption_rate']
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

            await ctx.send(
                f"Статус маяка {beacon['beacon_id']}:\n"
                f"🔋 Топливо: ~{beacon['current_fuel']:.0f}"
                f"(⏳ Осталось ~{hours_remaining_fuel:.1f} часов)\n"
                f"🔄 Прочность: {beacon['current_lifetime']:.2f}% ({status_msg})\n"
                f"📊 Приоритет: {priority_text}")

        else:
            cursor.execute('SELECT * FROM beacons ORDER BY beacon_id')
            beacons = cursor.fetchall()

            if not beacons:
                await ctx.send("Нет активных маяков")
                return

            message = "Статус всех маяков:\n\n"
            for beacon in beacons:
                if beacon['fuel_consumption_rate'] == 2:
                    priority_text = "🟢 Низкий(3)"
                elif beacon['fuel_consumption_rate'] == 1.5:
                    priority_text = "🟡 Средний(2)"
                elif beacon['fuel_consumption_rate'] == 1:
                    priority_text = "🔴 Высокий(1)"
                message += (
                    f"- {beacon['beacon_id']}\n"
                    f"🔋 Топливо: ~{beacon['current_fuel']:.0f}\n"
                    f"🔄 Прочность: {beacon['current_lifetime']:.2f}%\n"
                    f"📊 Приоритет: {priority_text}\n\n"
                )

            await ctx.send(message)
    except Exception as e:
        await ctx.send(f"Ошибка: {str(e)}")
    finally:
        conn.close()


@bot.command()
async def edit(ctx, beacon_id: str, priority: int = 2, current_fuel: float = None, current_lifetime: float = None):
    """Редактировать данные маяка по ID"""
    updates = []
    params = []
    reset_status = False

    if priority is not None:
        if priority not in [1, 2, 3]:
            await ctx.send("Ошибка: приоритет должен быть 1, 2 или 3\n"
                           "1 - высокий\n2 - средний\n3 - низкий")
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
            await ctx.send(f"Ошибка: значение топлива не может превышать {MAX_FUEL}")
            return
        updates.append("current_fuel = ?")
        params.append(current_fuel)
        reset_status = reset_status or ((current_fuel / MAX_FUEL) * 100 >= 20)

    if current_lifetime is not None:
        if current_lifetime > MAX_LIFETIME:
            await ctx.send(f"Ошибка: срок действия не может превышать {MAX_LIFETIME}")
            return
        updates.append("current_lifetime = ?")
        params.append(current_lifetime)
        reset_status = reset_status or (current_lifetime >= 20)

    if not updates:
        await ctx.send("Не указаны данные для обновления!")
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
            await ctx.send(f"Маяк {beacon_id} не найден!")
        else:
            await ctx.send(f"Данные маяка {beacon_id} успешно обновлены!")
    finally:
        conn.close()


@bot.command()
async def delete(ctx, beacon_id: str):
    """Удалить маяк по ID"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM beacons WHERE beacon_id = ?', (beacon_id,))
    conn.commit()

    if cursor.rowcount == 0:
        await ctx.send(f"Маяк с ID {beacon_id} не найден!")
    else:
        await ctx.send(f"Маяк {beacon_id} успешно удалён!")

    conn.close()


@bot.command()
async def clear(ctx):
    """Удалить все маяки (требуется подтверждение)"""
    await ctx.send("Вы уверены, что хотите удалить ВСЕ маяки? Напишите 'да' для продолжения.")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'да'

    try:
        await bot.wait_for('message', check=check, timeout=30.0)
    except TimeoutError:
        await ctx.send("Время ожидания истекло. Очистка отменена.")
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM beacons')
        conn.commit()
        await ctx.send("Все маяки успешно удалены!")
    finally:
        conn.close()


@bot.command()
async def ping(ctx):
    """Бот жив?"""
    await ctx.send("pong")


bot.run(os.getenv("TOKEN"))
