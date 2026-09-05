# beaconMonitor

Discord-бот для учёта маяков в Anvil Empires: топливо, прочность, приоритет, алерты и таймер реликвии.

## Структура

```
main.py              # точка входа
bot.py               # BeaconBot (Client + CommandTree + RelicTimer)
config.py            # .env и игровые константы
handlers/            # slash-команды и UI
  beacons.py         # /beacon …
  relic.py           # /relic …
  events.py          # on_ready
  views/             # View, Modal, Select
services/
  database.py        # SQLite
  beacon_service.py  # decay, алерты, фоновый цикл
  relic_service.py   # RelicTimer + relic_events
utils/               # логи, embed, форматирование
data/beacons.db      # база (создаётся при первом запуске)
logs/                # actions.log, errors.log
```

## Переменные окружения (.env)

| Переменная | Описание |
|------------|----------|
| `TOKEN` | Токен Discord-бота |
| `GUILD` | ID гильдии для регистрации slash-команд |
| `RELIC_CHANNEL_ID` | Канал уведомлений о реликвии |
| `RELIC_LINK_MESSAGE_ROLES` | Ссылка на сообщение для подписки/отписки на роль уведомлений |
| `RELIC_QRF_ROLE_ID` | Роль для пинга в предупреждении о реликвии |
| `ALERT_CHANNEL_ID` | Единый канал алертов (маяки, upkeep, сытость, сезоны) |
| `PANEL_CHANNEL_ID` | Канал постоянных панелей (Владения Новгорода, реликвия, сезоны); legacy `UPKEEP_PANEL_CHANNEL_ID` |
| `SILVER_EMOJI_ID` | ID кастомного эмодзи серебра |

## Локальный запуск

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

## Docker

```bash
docker compose build
docker compose up -d
```

Тома: `./data`, `./logs`. Порт в compose: `8451`.

## Команды

- `/beacon add|menu|refuel|status|edit|delete|clear`
- `/relic start|cancel|status`
- `/season setup|delete`
- `/help` `/ping`

## Логи

- `logs/actions.log` — `beacon_actions`, `relic_actions`, `upkeep_actions`, `season_actions`, `feed_actions`, `system`
- `logs/errors.log` — ошибки
