import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import settings

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "metadata.sqlite3")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS procedures (
                user_id TEXT NOT NULL,
                agent_role TEXT NOT NULL,
                procedure TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, agent_role)
            );
            CREATE TABLE IF NOT EXISTS temporal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_procedure(user_id: str, agent_role: str, default: str) -> str:
    with connection() as conn:
        row = conn.execute(
            "SELECT procedure FROM procedures WHERE user_id = ? AND agent_role = ?",
            (user_id, agent_role),
        ).fetchone()
    return row[0] if row else default


def update_procedure(user_id: str, agent_role: str, procedure: str) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO procedures(user_id, agent_role, procedure, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, agent_role) DO UPDATE SET
              procedure = excluded.procedure,
              updated_at = excluded.updated_at
            """,
            (user_id, agent_role, procedure, datetime.now().isoformat()),
        )


def record_event(user_id: str, event_type: str, details: dict) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO temporal_events(user_id, event_type, details, created_at) VALUES (?, ?, ?, ?)",
            (user_id, event_type, json.dumps(details), datetime.now().isoformat()),
        )


def list_events(user_id: str) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT event_type, details, created_at FROM temporal_events WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [
        {"event_type": event_type, "details": json.loads(details), "timestamp": created_at}
        for event_type, details, created_at in rows
    ]


def list_procedures(user_id: str) -> dict[str, str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT agent_role, procedure FROM procedures WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {agent_role: procedure for agent_role, procedure in rows}


def reset_user_metadata(user_id: str) -> dict[str, int]:
    with connection() as conn:
        procedure_count = conn.execute(
            "SELECT COUNT(*) FROM procedures WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(*) FROM temporal_events WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        conn.execute("DELETE FROM procedures WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM temporal_events WHERE user_id = ?", (user_id,))
    return {"procedures": procedure_count, "events": event_count}
