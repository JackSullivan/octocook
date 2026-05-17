"""SQLite layer for session state and historical step actuals.

A "session" is one cooking gathering: a chosen set of recipes, a kitchen,
a cook count, and the frozen schedule the scheduler produced. Per-step
progress (started_at / completed_at / actual_seconds) is tracked in
session_steps and rolled up into step_actuals for cross-session history.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


_DEFAULT_DB_PATH = Path(__file__).parent / "octocook.db"


def _db_path() -> Path:
    return Path(os.environ.get("OCTOCOOK_DB", _DEFAULT_DB_PATH))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    num_cooks INTEGER NOT NULL,
    kitchen TEXT NOT NULL,
    recipe_titles TEXT NOT NULL,    -- JSON array
    schedule_json TEXT NOT NULL     -- full schedule dict, frozen at creation
);

CREATE TABLE IF NOT EXISTS session_steps (
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    actual_seconds INTEGER,
    PRIMARY KEY (session_id, step_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS step_actuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_title TEXT NOT NULL,
    step_description TEXT NOT NULL,
    estimated_seconds INTEGER NOT NULL,
    actual_seconds INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_step_actuals_key
    ON step_actuals (recipe_title, step_description);
"""


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_session(
    *,
    recipe_titles: list[str],
    kitchen: str,
    num_cooks: int,
    schedule: dict,
) -> str:
    session_id = uuid.uuid4().hex[:12]
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, num_cooks, kitchen, recipe_titles, schedule_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                _now_iso(),
                num_cooks,
                kitchen,
                json.dumps(recipe_titles),
                json.dumps(schedule),
            ),
        )
    return session_id


def get_session(session_id: str) -> dict | None:
    """Return the session row + per-step progress, or None if not found."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        steps = conn.execute(
            "SELECT step_id, started_at, completed_at, actual_seconds "
            "FROM session_steps WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "num_cooks": row["num_cooks"],
        "kitchen": row["kitchen"],
        "recipe_titles": json.loads(row["recipe_titles"]),
        "schedule": json.loads(row["schedule_json"]),
        "step_state": {
            s["step_id"]: {
                "started_at": s["started_at"],
                "completed_at": s["completed_at"],
                "actual_seconds": s["actual_seconds"],
            }
            for s in steps
        },
    }


def mark_step_started(session_id: str, step_id: str) -> str:
    """Record that a cook has started a step. Returns the ISO timestamp."""
    ts = _now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO session_steps (session_id, step_id, started_at) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id, step_id) DO UPDATE SET started_at = excluded.started_at, "
            "completed_at = NULL, actual_seconds = NULL",
            (session_id, step_id, ts),
        )
    return ts


def mark_step_done(
    session_id: str,
    step_id: str,
    actual_seconds: int | None = None,
) -> dict:
    """Mark a step done. If actual_seconds is None and started_at is set,
    derive it from the elapsed wall-clock time. Also records to step_actuals
    for future estimation when actuals are available.
    """
    completed_at = _now_iso()
    with connect() as conn:
        existing = conn.execute(
            "SELECT started_at FROM session_steps WHERE session_id = ? AND step_id = ?",
            (session_id, step_id),
        ).fetchone()

        if actual_seconds is None and existing and existing["started_at"]:
            start_dt = datetime.fromisoformat(existing["started_at"])
            end_dt = datetime.fromisoformat(completed_at)
            actual_seconds = max(1, int((end_dt - start_dt).total_seconds()))

        conn.execute(
            "INSERT INTO session_steps (session_id, step_id, completed_at, actual_seconds) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id, step_id) DO UPDATE SET "
            "completed_at = excluded.completed_at, actual_seconds = excluded.actual_seconds",
            (session_id, step_id, completed_at, actual_seconds),
        )

        # Roll up into step_actuals so the description -> actual_seconds mapping
        # accumulates across sessions. We pull description + estimate from the
        # frozen schedule on the session row.
        if actual_seconds is not None:
            sess = conn.execute(
                "SELECT schedule_json FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if sess:
                schedule = json.loads(sess["schedule_json"])
                step = next(
                    (s for s in schedule.get("steps", []) if s["step_id"] == step_id),
                    None,
                )
                if step is not None:
                    conn.execute(
                        "INSERT INTO step_actuals "
                        "(recipe_title, step_description, estimated_seconds, "
                        "actual_seconds, recorded_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            step["recipe"],
                            step["description"],
                            int(step["duration_min"]) * 60,
                            actual_seconds,
                            completed_at,
                        ),
                    )

    return {"completed_at": completed_at, "actual_seconds": actual_seconds}
