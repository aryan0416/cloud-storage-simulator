"""
database.py
-----------
All SQLite code lives in this module: the connection, table creation and the
queries used by the other modules.

Rules followed here:
* Only PARAMETERISED queries are used (the "?" placeholders). User input is
  never joined into an SQL string, which prevents SQL injection.
* Every function opens a short-lived connection and closes it again, so data
  is written to disk immediately and survives app restarts.
"""

import sqlite3
from contextlib import closing
from datetime import datetime

import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_str() -> str:
    """Current local time as a readable string, e.g. '2026-01-31 14:05:09'."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_connection() -> sqlite3.Connection:
    """Open a connection to the SQLite file. Rows behave like dictionaries."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row          # access columns by name: row["tier"]
    return conn


def _execute(sql: str, params: tuple = ()) -> int:
    """Run an INSERT/UPDATE/DELETE and return the id of the last inserted row."""
    with closing(get_connection()) as conn:
        with conn:                          # commits on success, rolls back on error
            cursor = conn.execute(sql, params)
            return cursor.lastrowid


def _fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT and return every row as a plain dictionary."""
    with closing(get_connection()) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def _fetch_one(sql: str, params: tuple = ()) -> dict | None:
    """Run a SELECT and return the first row as a dictionary (or None)."""
    rows = _fetch_all(sql, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create the data folders and all tables if they do not exist yet."""
    for folder in (config.DATA_DIR, config.STORAGE_DIR,
                   config.SECONDARY_DIR, config.BACKUP_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,          -- PBKDF2 hash (hex), never plain text
        salt          TEXT NOT NULL,          -- random salt (hex)
        role          TEXT NOT NULL           -- Owner / Contributor / Reader
    );

    CREATE TABLE IF NOT EXISTS files (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        original_name        TEXT NOT NULL,   -- sanitised name shown to users
        stored_name          TEXT NOT NULL,   -- UUID + name used on disk
        size_bytes           INTEGER NOT NULL,
        upload_date          TEXT NOT NULL,
        tier                 TEXT NOT NULL,   -- Hot / Cool / Cold / Archive
        redundancy           TEXT NOT NULL,   -- LRS / GRS
        tier_changed_at      TEXT NOT NULL,   -- used for early-deletion rules
        rehydration_status   TEXT NOT NULL DEFAULT 'None',  -- None / Rehydrating
        rehydrate_target     TEXT,            -- Hot / Cool while rehydrating
        rehydrate_started_at TEXT,
        uploaded_by          TEXT
    );

    CREATE TABLE IF NOT EXISTS backups (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id          INTEGER,             -- original file id (may be deleted later)
        original_name    TEXT NOT NULL,
        backup_path      TEXT NOT NULL,       -- file name inside data/backups/
        size_bytes       INTEGER NOT NULL,
        created_at       TEXT NOT NULL,
        created_by       TEXT
    );

    CREATE TABLE IF NOT EXISTS activity_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        username  TEXT,
        role      TEXT,
        action    TEXT NOT NULL,
        filename  TEXT,
        details   TEXT
    );

    -- Simple key/value table for simulator state (e.g. primary region outage).
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """
    with closing(get_connection()) as conn:
        with conn:
            conn.executescript(schema)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def get_user(username: str) -> dict | None:
    return _fetch_one("SELECT * FROM users WHERE username = ?", (username,))


def add_user(username: str, password_hash: str, salt: str, role: str) -> None:
    _execute(
        "INSERT OR IGNORE INTO users (username, password_hash, salt, role) "
        "VALUES (?, ?, ?, ?)",
        (username, password_hash, salt, role),
    )


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def add_file(original_name: str, stored_name: str, size_bytes: int,
             tier: str, redundancy: str, uploaded_by: str) -> int:
    timestamp = now_str()
    return _execute(
        "INSERT INTO files (original_name, stored_name, size_bytes, upload_date, "
        "tier, redundancy, tier_changed_at, uploaded_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (original_name, stored_name, size_bytes, timestamp,
         tier, redundancy, timestamp, uploaded_by),
    )


def get_all_files() -> list[dict]:
    return _fetch_all("SELECT * FROM files ORDER BY id DESC")


def get_file(file_id: int) -> dict | None:
    return _fetch_one("SELECT * FROM files WHERE id = ?", (file_id,))


def get_total_size() -> int:
    row = _fetch_one("SELECT COALESCE(SUM(size_bytes), 0) AS total FROM files")
    return int(row["total"])


def update_file_tier(file_id: int, new_tier: str) -> None:
    _execute(
        "UPDATE files SET tier = ?, tier_changed_at = ?, rehydration_status = 'None', "
        "rehydrate_target = NULL, rehydrate_started_at = NULL WHERE id = ?",
        (new_tier, now_str(), file_id),
    )


def update_file_size(file_id: int, size_bytes: int) -> None:
    _execute("UPDATE files SET size_bytes = ? WHERE id = ?", (size_bytes, file_id))


def set_rehydrating(file_id: int, target_tier: str) -> None:
    _execute(
        "UPDATE files SET rehydration_status = 'Rehydrating', rehydrate_target = ?, "
        "rehydrate_started_at = ? WHERE id = ?",
        (target_tier, now_str(), file_id),
    )


def get_rehydrating_files() -> list[dict]:
    return _fetch_all("SELECT * FROM files WHERE rehydration_status = 'Rehydrating'")


def delete_file_record(file_id: int) -> None:
    _execute("DELETE FROM files WHERE id = ?", (file_id,))


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
def add_backup(file_id: int, original_name: str, backup_path: str,
               size_bytes: int, created_by: str) -> int:
    return _execute(
        "INSERT INTO backups (file_id, original_name, backup_path, size_bytes, "
        "created_at, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (file_id, original_name, backup_path, size_bytes, now_str(), created_by),
    )


def get_all_backups() -> list[dict]:
    return _fetch_all("SELECT * FROM backups ORDER BY id DESC")


def get_backup(backup_id: int) -> dict | None:
    return _fetch_one("SELECT * FROM backups WHERE id = ?", (backup_id,))


def count_backups() -> int:
    row = _fetch_one("SELECT COUNT(*) AS n FROM backups")
    return int(row["n"])


def relink_backups(old_file_id: int, new_file_id: int) -> None:
    """After a deleted file is re-created from backup, point its backups at the new id."""
    _execute("UPDATE backups SET file_id = ? WHERE file_id = ?",
             (new_file_id, old_file_id))


# ---------------------------------------------------------------------------
# Activity log (simulates Azure Monitor / Activity Log)
# ---------------------------------------------------------------------------
def log_activity(username: str, role: str, action: str,
                 filename: str = "", details: str = "") -> None:
    """Record one action. Logging must never crash the app, so errors are ignored."""
    try:
        _execute(
            "INSERT INTO activity_log (timestamp, username, role, action, filename, details) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now_str(), username, role, action, filename, details),
        )
    except sqlite3.Error as exc:
        print(f"[activity log] could not write entry: {exc}")


def get_activity(limit: int | None = None) -> list[dict]:
    if limit:
        return _fetch_all("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))
    return _fetch_all("SELECT * FROM activity_log ORDER BY id DESC")


# ---------------------------------------------------------------------------
# Settings (simulator state)
# ---------------------------------------------------------------------------
def get_setting(key: str, default: str = "") -> str:
    row = _fetch_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    _execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
