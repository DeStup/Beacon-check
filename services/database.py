"""Р Р°Р±РѕС‚Р° СЃ SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Iterable, Optional

import config

Row = sqlite3.Row


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """РљРѕРЅС‚РµРєСЃС‚РЅС‹Р№ РјРµРЅРµРґР¶РµСЂ СЃРѕРµРґРёРЅРµРЅРёСЏ СЃ Р‘Р”."""
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
    """РЎРѕР·РґР°С‘С‚ С‚Р°Р±Р»РёС†С‹, РµСЃР»Рё РёС… РµС‰С‘ РЅРµС‚."""
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
                ended_at TEXT,
                started_by TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relic_events_active
            ON relic_events (channel_id, status)
            """
        )
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(relic_events)")
        }
        if "started_by" not in columns:
            conn.execute(
                "ALTER TABLE relic_events ADD COLUMN started_by TEXT"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upkeep_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                silver_per_hour REAL NOT NULL,
                silver_amount REAL NOT NULL,
                last_updated TEXT NOT NULL,
                low_warning_sent INTEGER NOT NULL DEFAULT 0,
                created_by TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_upkeep_objects_name
            ON upkeep_objects (name)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upkeep_panel (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS relic_panel (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS season_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                season_key TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS season_panel (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )
            """
        )


def list_upkeep_summary() -> list[Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                """
                SELECT id, name, silver_per_hour, silver_amount, last_updated
                FROM upkeep_objects
                ORDER BY id ASC
                """
            ).fetchall()
        )


def list_all_upkeep() -> list[Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                "SELECT * FROM upkeep_objects ORDER BY id ASC"
            ).fetchall()
        )


def get_upkeep_by_name(name: str) -> Optional[Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM upkeep_objects WHERE name = ?",
            (name,),
        ).fetchone()


def get_upkeep_by_id(object_id: int) -> Optional[Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM upkeep_objects WHERE id = ?",
            (object_id,),
        ).fetchone()


def upkeep_exists(name: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM upkeep_objects WHERE name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None


def insert_upkeep(
    *,
    name: str,
    silver_per_hour: float,
    silver_amount: float,
    created_by: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO upkeep_objects (
                name, silver_per_hour, silver_amount, last_updated,
                low_warning_sent, created_by
            ) VALUES (?, ?, ?, ?, 0, ?)
            """,
            (
                name,
                silver_per_hour,
                silver_amount,
                datetime.now().isoformat(),
                created_by,
            ),
        )


def delete_upkeep(name: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM upkeep_objects WHERE name = ?",
            (name,),
        )
        return cursor.rowcount > 0


def clear_all_upkeep() -> list[str]:
    """РЈРґР°Р»СЏРµС‚ РІСЃРµ РѕР±СЉРµРєС‚С‹ upkeep Рё РІРѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє РёРјС‘РЅ."""
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM upkeep_objects").fetchall()
        names = [row["name"] for row in rows]
        conn.execute("DELETE FROM upkeep_objects")
        return names


def update_upkeep(
    object_id: int,
    *,
    name: Optional[str] = None,
    silver_per_hour: Optional[float] = None,
    silver_amount: Optional[float] = None,
    last_updated: Optional[str] = None,
    low_warning_sent: Optional[bool] = None,
) -> bool:
    set_parts: list[str] = []
    params: list[Any] = []
    if name is not None:
        set_parts.append("name = ?")
        params.append(name)
    if silver_per_hour is not None:
        set_parts.append("silver_per_hour = ?")
        params.append(silver_per_hour)
    if silver_amount is not None:
        set_parts.append("silver_amount = ?")
        params.append(silver_amount)
    if last_updated is not None:
        set_parts.append("last_updated = ?")
        params.append(last_updated)
    if low_warning_sent is not None:
        set_parts.append("low_warning_sent = ?")
        params.append(1 if low_warning_sent else 0)
    if not set_parts:
        return False
    params.append(object_id)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE upkeep_objects SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        return cursor.rowcount > 0


def apply_upkeep_decay_update(
    object_id: int,
    silver_amount: float,
    last_updated: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE upkeep_objects
            SET silver_amount = ?, last_updated = ?
            WHERE id = ?
            """,
            (silver_amount, last_updated, object_id),
        )


def set_upkeep_low_warning(object_id: int, sent: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE upkeep_objects SET low_warning_sent = ? WHERE id = ?",
            (1 if sent else 0, object_id),
        )


def fetch_all_upkeep_for_update() -> list[Row]:
    with get_connection() as conn:
        return list(conn.execute("SELECT * FROM upkeep_objects").fetchall())


def get_upkeep_panel() -> Optional[tuple[int, int]]:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ (channel_id, message_id) РїР°РЅРµР»Рё РќРѕРІРіРѕСЂРѕРґР° РёР»Рё None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT channel_id, message_id FROM upkeep_panel WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return int(row["channel_id"]), int(row["message_id"])


def set_upkeep_panel(channel_id: int, message_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO upkeep_panel (id, channel_id, message_id)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_id = excluded.message_id
            """,
            (channel_id, message_id),
        )


def clear_upkeep_panel() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM upkeep_panel WHERE id = 1")


def get_relic_panel() -> Optional[tuple[int, int]]:
    """Возвращает (channel_id, message_id) панели реликвии или None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT channel_id, message_id FROM relic_panel WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return int(row["channel_id"]), int(row["message_id"])


def set_relic_panel(channel_id: int, message_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO relic_panel (id, channel_id, message_id)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_id = excluded.message_id
            """,
            (channel_id, message_id),
        )


def clear_relic_panel() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM relic_panel WHERE id = 1")


def get_season_state() -> Optional[Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM season_state WHERE id = 1"
        ).fetchone()


def set_season_state(season_key: str, started_at: str) -> None:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO season_state (id, season_key, started_at, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                season_key = excluded.season_key,
                started_at = excluded.started_at,
                updated_at = excluded.updated_at
            """,
            (season_key, started_at, now),
        )


def clear_season_state() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM season_state WHERE id = 1")


def get_season_panel() -> Optional[tuple[int, int]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT channel_id, message_id FROM season_panel WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return int(row["channel_id"]), int(row["message_id"])


def set_season_panel(channel_id: int, message_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO season_panel (id, channel_id, message_id)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_id = excluded.message_id
            """,
            (channel_id, message_id),
        )


def clear_season_panel() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM season_panel WHERE id = 1")


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
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM beacons WHERE beacon_id = ? LIMIT 1",
            (beacon_id,),
        ).fetchone()
        return row is not None


def insert_beacon(
    *,
    beacon_id: str,
    current_fuel: float,
    current_lifetime: float,
    fuel_consumption_rate: float,
    message_link: str,
    username: str,
) -> None:
    with get_connection() as conn:
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
    """РЈРґР°Р»СЏРµС‚ РІСЃРµ РјР°СЏРєРё Рё РІРѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє СѓРґР°Р»С‘РЅРЅС‹С… ID."""
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
    """РћР±РЅРѕРІР»СЏРµС‚ РїРѕР»СЏ РјР°СЏРєР°. РљР»СЋС‡Рё вЂ” РёРјРµРЅР° РєРѕР»РѕРЅРѕРє."""
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
    """Р”РѕР±Р°РІР»СЏРµС‚ С‚РѕРїР»РёРІРѕ. Р’РѕР·РІСЂР°С‰Р°РµС‚ dict СЃ СЂРµР·СѓР»СЊС‚Р°С‚РѕРј РёР»Рё None РµСЃР»Рё РЅРµ РЅР°Р№РґРµРЅ."""
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
    """РЈРІРµР»РёС‡РёРІР°РµС‚ created / refueled / repaired РЅР° 1."""
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
    started_by: Optional[str] = None,
) -> int:
    """РЎРѕР·РґР°С‘С‚ Р°РєС‚РёРІРЅРѕРµ СЃРѕР±С‹С‚РёРµ; РїСЂРµРґС‹РґСѓС‰РёРµ active РґР»СЏ РєР°РЅР°Р»Р° Р·Р°РєСЂС‹РІР°РµС‚ РєР°Рє cancelled."""
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
                channel_id, started_at, duration_minutes,
                warning_sent, status, started_by
            ) VALUES (?, ?, ?, 0, 'active', ?)
            """,
            (channel_id, started_at.isoformat(), duration_minutes, started_by),
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
    """РћС‚РјРµРЅСЏРµС‚ Р°РєС‚РёРІРЅРѕРµ СЃРѕР±С‹С‚РёРµ РєР°РЅР°Р»Р°. True РµСЃР»Рё Р±С‹Р»Рѕ С‡С‚Рѕ РѕС‚РјРµРЅСЏС‚СЊ."""
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

