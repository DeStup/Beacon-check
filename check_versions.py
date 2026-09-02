import sys
import discord
import dotenv
import sqlite3
import logging

print("="*50)
print("ПРОВЕРКА ВЕРСИЙ ПАКЕТОВ")
print("="*50)

# Версия Python
print(f"Python: {sys.version}")

# Discord.py
try:
    print(f"discord.py: {discord.__version__}")
except:
    print("discord.py: не удалось определить версию")

# Python-dotenv
try:
    print(f"python-dotenv: {dotenv.__version__}")
except:
    print("python-dotenv: не удалось определить версию")

# SQLite3
print(f"sqlite3: {sqlite3.sqlite_version}")

# logging - встроенный модуль
print(f"logging: встроенный модуль")

print("\n" + "="*50)
print("ДЕТАЛЬНАЯ ИНФОРМАЦИЯ:")
print("="*50)

# Детальная информация о discord.py
try:
    import pkg_resources
    discord_version = pkg_resources.get_distribution("discord.py").version
    print(f"discord.py (через pkg_resources): {discord_version}")
except:
    pass

# Все установленные пакеты
print("\nУстановленные пакеты в окружении:")
import subprocess
result = subprocess.run(['pip', 'freeze'], capture_output=True, text=True)
print(result.stdout)