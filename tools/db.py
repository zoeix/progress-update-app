from __future__ import annotations

import json
import sqlite3
from typing import Any

from tools.config import (
    DATA_DIR,
    DB_PATH,
    STATE_EDITING,
    STATE_NEEDS_MORE_INFO,
    STATE_READY_FOR_REVIEW,
    utc_now,
)


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                state TEXT NOT NULL,
                running_summary TEXT NOT NULL DEFAULT '',
                last_error TEXT,
                last_notice TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS progress_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                raw_input TEXT NOT NULL,
                formatted_json TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                questions_json TEXT NOT NULL,
                final_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                entry_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                reason TEXT NOT NULL,
                priority TEXT NOT NULL,
                target_field TEXT NOT NULL DEFAULT 'notes',
                status TEXT NOT NULL DEFAULT 'unresolved',
                review_reason TEXT NOT NULL DEFAULT '',
                previous_question_id TEXT NOT NULL DEFAULT '',
                answer TEXT,
                answered_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (entry_id) REFERENCES progress_entries(id)
            );

            CREATE TABLE IF NOT EXISTS codex_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                entry_id INTEGER,
                role TEXT NOT NULL,
                prompt_snapshot TEXT NOT NULL,
                output_text TEXT NOT NULL DEFAULT '',
                output_json TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (entry_id) REFERENCES progress_entries(id)
            );

            CREATE TABLE IF NOT EXISTS clickup_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL,
                synced_at TEXT NOT NULL
            );
            """
        )
        question_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(questions)").fetchall()
        }
        if "target_field" not in question_columns:
            conn.execute("ALTER TABLE questions ADD COLUMN target_field TEXT NOT NULL DEFAULT 'notes'")
        if "status" not in question_columns:
            conn.execute("ALTER TABLE questions ADD COLUMN status TEXT NOT NULL DEFAULT 'unresolved'")
        if "review_reason" not in question_columns:
            conn.execute("ALTER TABLE questions ADD COLUMN review_reason TEXT NOT NULL DEFAULT ''")
        if "previous_question_id" not in question_columns:
            conn.execute("ALTER TABLE questions ADD COLUMN previous_question_id TEXT NOT NULL DEFAULT ''")
        session_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "last_error" not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN last_error TEXT")
        if "last_notice" not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN last_notice TEXT")
        existing = conn.execute("SELECT id FROM sessions LIMIT 1").fetchone()
        if existing is None:
            now = utc_now()
            conn.execute(
                """
                INSERT INTO sessions (title, state, running_summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("Default progress update", STATE_EDITING, "", now, now),
            )


def get_session(conn: sqlite3.Connection) -> sqlite3.Row:
    session = conn.execute("SELECT * FROM sessions ORDER BY id LIMIT 1").fetchone()
    if session is None:
        init_db()
        session = conn.execute("SELECT * FROM sessions ORDER BY id LIMIT 1").fetchone()
    return session


def get_latest_entry(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM progress_entries
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()


def get_questions(conn: sqlite3.Connection, entry_id: int | None) -> list[sqlite3.Row]:
    if entry_id is None:
        return []
    return conn.execute(
        """
        SELECT * FROM questions
        WHERE entry_id = ?
        ORDER BY id
        """,
        (entry_id,),
    ).fetchall()


def set_session_error(conn: sqlite3.Connection, session_id: int, error: str | None) -> None:
    conn.execute(
        """
        UPDATE sessions
        SET last_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (error, utc_now(), session_id),
    )


def set_session_notice(conn: sqlite3.Connection, session_id: int, notice: str | None) -> None:
    conn.execute(
        """
        UPDATE sessions
        SET last_notice = ?, updated_at = ?
        WHERE id = ?
        """,
        (notice, utc_now(), session_id),
    )


def save_refinement(
    conn: sqlite3.Connection,
    session_id: int,
    raw_input: str,
    formatted: dict[str, Any],
    evaluation: dict[str, Any],
    question_result: dict[str, list[dict[str, str]]],
    final_text: str,
    now: str,
) -> int:
    questions = question_result["questions"]
    cursor = conn.execute(
        """
        INSERT INTO progress_entries (
            session_id, raw_input, formatted_json, evaluation_json,
            questions_json, final_text, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            raw_input,
            json.dumps(formatted, ensure_ascii=False),
            json.dumps(evaluation, ensure_ascii=False),
            json.dumps(question_result, ensure_ascii=False),
            final_text,
            now,
        ),
    )
    entry_id = cursor.lastrowid
    for question in questions:
        conn.execute(
            """
            INSERT INTO questions (
                session_id, entry_id, question, reason, priority,
                target_field, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                entry_id,
                question["question"],
                question["reason"],
                question["priority"],
                question["target_field"],
                now,
            ),
        )
    next_state = STATE_READY_FOR_REVIEW if evaluation["ready_for_review"] else STATE_NEEDS_MORE_INFO
    conn.execute(
        """
        UPDATE sessions
        SET state = ?, running_summary = ?, last_error = NULL, last_notice = NULL, updated_at = ?
        WHERE id = ?
        """,
        (next_state, final_text, now, session_id),
    )
    return entry_id


def parse_json_field(row: sqlite3.Row | None, field: str, default: Any) -> Any:
    if row is None:
        return default
    value = row[field]
    if not value:
        return default
    return json.loads(value)


def serialize_latest_progress(conn: sqlite3.Connection) -> dict[str, Any]:
    session = get_session(conn)
    latest_entry = get_latest_entry(conn, session["id"])
    formatted = parse_json_field(latest_entry, "formatted_json", {}) if latest_entry else {}
    return {
        "session_id": session["id"],
        "entry_id": latest_entry["id"] if latest_entry else None,
        "final_text": latest_entry["final_text"] if latest_entry else "",
        "formatted": formatted,
    }


def reset_progress_data(conn: sqlite3.Connection) -> None:
    now = utc_now()
    session_id = get_session(conn)["id"]
    conn.execute("DELETE FROM questions WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM progress_entries WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM codex_runs WHERE session_id = ?", (session_id,))
    conn.execute(
        """
        UPDATE sessions
        SET state = ?, running_summary = '', last_error = NULL, last_notice = NULL, updated_at = ?
        WHERE id = ?
        """,
        (STATE_EDITING, now, session_id),
    )
