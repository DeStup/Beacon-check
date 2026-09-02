"""Работа с SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Iterable, Optional

import config

Row = sqlite3.Row


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Контекстный менеджер соединения с БД."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
    with get_connection() as conn:
        conn.execute(
            """
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
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created INTEGER DEFAULT 0,
                refueled INTEGER DEFAULT 0,
                repaired INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS relic_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                warning_sent INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                ended_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relic_events_active
            ON relic_events (channel_id, status)
            """
        )


def count_beacons() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM beacons").fetchone()
        return int(row["count"])


def list_beacon_ids() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT beacon_id FROM beacons ORDER BY beacon_id"
        ).fetchall()
        return [row["beacon_id"] for row in rows]


def list_beacons_summary() -> list[Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                """
                SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate
                FROM beacons
                ORDER BY beacon_id
                """
            ).fetchall()
        )


def list_all_beacons() -> list[Row]:
    with get_connection() as conn:
        return list(conn.execute("SELECT * FROM beacons ORDER BY beacon_id").fetchall())


def get_beacon(beacon_id: str) -> Optional[Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM beacons WHERE beacon_id = ?",
            (beacon_id,),
        ).fetchone()


def beacon_exists(beacon_id: str) -> bool:
    return get_beacon(beacon_id) is not None


def insert_beacon(
    *,
    beacon_id: str,
    current_fuel: float,
    current_lifetime: float,
    fuel_consumption_rate: float,
    message_link: str,
    username: str,
    image_url: Optional[str] = None,
) -> None:
    with get_connection() as conn:
        if image_url is not None:
            conn.execute(
                """
                INSERT INTO beacons (
                    beacon_id, current_fuel, current_lifetime, fuel_consumption_rate,
                    last_updated, low_status_sent, message_link, username, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    beacon_id,
                    current_fuel,
                    current_lifetime,
                    fuel_consumption_rate,
                    datetime.now().isoformat(),
                    False,
                    message_link,
                    username,
                    image_url,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO beacons (
                    beacon_id, current_fuel, current_lifetime, fuel_consumption_rate,
                    last_updated, low_status_sent, message_link, username
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    beacon_id,
                    current_fuel,
                    current_lifetime,
                    fuel_consumption_rate,
                    datetime.now().isoformat(),
                    False,
                    message_link,
                    username,
                ),
            )


def delete_beacon(beacon_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM beacons WHERE beacon_id = ?",
            (beacon_id,),
        )
        return cursor.rowcount > 0


def clear_all_beacons() -> list[str]:
    """Удаляет все маяки и возвращает список удалённых ID."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT beacon_id, current_fuel, current_lifetime, fuel_consumption_rate
            FROM beacons
            """
        ).fetchall()
        ids = [row["beacon_id"] for row in rows]
        conn.execute("DELETE FROM beacons")
        return ids


def update_beacon_fields(
    beacon_id: str,
    *,
    updates: dict[str, Any],
    low_status_sent: Optional[bool] = None,
) -> bool:
    """Обновляет поля маяка. Ключи — имена колонок."""
    if not updates and low_status_sent is None:
        return False

    set_parts: list[str] = []
    params: list[Any] = []
    for column, value in updates.items():
        set_parts.append(f"{column} = ?")
        params.append(value)

    if low_status_sent is not None:
        set_parts.append("low_status_sent = ?")
        params.append(low_status_sent)

    set_parts.append("last_updated = CURRENT_TIMESTAMP")
    params.append(beacon_id)

    query = f"UPDATE beacons SET {', '.join(set_parts)} WHERE beacon_id = ?"
    with get_connection() as conn:
        cursor = conn.execute(query, params)
        return cursor.rowcount > 0


def refuel_beacon(
    beacon_id: str,
    amount: float,
) -> Optional[dict[str, Any]]:
    """Добавляет топливо. Возвращает dict с результатом или None если не найден."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT current_fuel, current_lifetime, message_link
            FROM beacons WHERE beacon_id = ?
            """,
            (beacon_id,),
        ).fetchone()
        if not row:
            return None

        current = float(row["current_fuel"])
        current_lifetime = float(row["current_lifetime"])
        new_fuel = min(current + amount, config.MAX_FUEL)
        added = new_fuel - current
        fuel_percent = (new_fuel / config.MAX_FUEL) * 100
        reset_status = fuel_percent >= config.WARNING_THRESHOLD and (
            current_lifetime >= config.WARNING_THRESHOLD
        )

        conn.execute(
            """
            UPDATE beacons
            SET current_fuel = ?, last_updated = ?, low_status_sent = ?
            WHERE beacon_id = ?
            """,
            (
                new_fuel,
                datetime.now().isoformat(),
                not reset_status,
                beacon_id,
            ),
        )
        return {
            "old_fuel": current,
            "new_fuel": new_fuel,
            "added": added,
            "amount_requested": amount,
            "message_link": row["message_link"],
        }


def increment_user_stat(
    user_id: str,
    username: str,
    stat: str,
) -> None:
    """Увеличивает created / refueled / repaired на 1."""
    if stat not in {"created", "refueled", "repaired"}:
        raise ValueError(f"Unknown user stat: {stat}")

    with get_connection() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if user:
            conn.execute(
                f"UPDATE users SET {stat} = {stat} + 1, username = ? WHERE user_id = ?",
                (username, user_id),
            )
        else:
            created = 1 if stat == "created" else 0
            refueled = 1 if stat == "refueled" else 0
            repaired = 1 if stat == "repaired" else 0
            conn.execute(
                """
                INSERT INTO users (user_id, username, created, refueled, repaired)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, created, refueled, repaired),
            )


def fetch_all_for_update() -> list[Row]:
    with get_connection() as conn:
        return list(conn.execute("SELECT * FROM beacons").fetchall())


def apply_decay_update(
    beacon_db_id: int,
    new_fuel: float,
    new_lifetime: float,
    last_updated: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE beacons
            SET current_fuel = ?, current_lifetime = ?, last_updated = ?
            WHERE id = ?
            """,
            (new_fuel, new_lifetime, last_updated, beacon_db_id),
        )


def set_low_status(beacon_id: str, sent: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE beacons
            SET low_status_sent = ?, last_updated = ?
            WHERE beacon_id = ?
            """,
            (sent, datetime.now().isoformat(), beacon_id),
        )


# --- relic_events ---


def get_active_relic_event(channel_id: int) -> Optional[Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM relic_events
            WHERE channel_id = ? AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel_id,),
        ).fetchone()


def create_relic_event(
    *,
    channel_id: int,
    started_at: datetime,
    duration_minutes: int,
) -> int:
    """Создаёт активное событие; предыдущие active для канала закрывает как cancelled."""
    with get_connection() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            """
            UPDATE relic_events
            SET status = 'cancelled', ended_at = ?
            WHERE channel_id = ? AND status = 'active'
            """,
            (now, channel_id),
        )
        cursor = conn.execute(
            """
            INSERT INTO relic_events (
                channel_id, started_at, duration_minutes, warning_sent, status
            ) VALUES (?, ?, ?, 0, 'active')
            """,
            (channel_id, started_at.isoformat(), duration_minutes),
        )
        return int(cursor.lastrowid)


def set_relic_warning_sent(event_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE relic_events
            SET warning_sent = 1
            WHERE id = ? AND status = 'active'
            """,
            (event_id,),
        )


def finish_relic_event(event_id: int, status: str) -> None:
    """status: completed | cancelled."""
    if status not in {"completed", "cancelled"}:
        raise ValueError(f"Invalid relic status: {status}")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE relic_events
            SET status = ?, ended_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (status, datetime.now().isoformat(), event_id),
        )


def cancel_active_relic_event(channel_id: int) -> bool:
    """Отменяет активное событие канала. True если было что отменять."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE relic_events
            SET status = 'cancelled', ended_at = ?
            WHERE channel_id = ? AND status = 'active'
            """,
            (datetime.now().isoformat(), channel_id),
        )
        return cursor.rowcount > 0
