"""SQLite connectivity helpers. Plain sqlite3 keeps the app dependency-free and fast."""
import sqlite3
from typing import Iterator

from app.config import BASE_DIR, settings

SCHEMA_FILE = BASE_DIR / "db" / "schema.sql"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, committed on success."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first release; created on older databases at startup.
MIGRATIONS = [("applications", "decision_reason_te", "TEXT"), ("alerts", "message_te", "TEXT")]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    for table, column, sql_type in MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    conn.commit()


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def fetch_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None
