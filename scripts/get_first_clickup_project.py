from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "data" / "app.db"


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Return the first synced ClickUp task from the local DB.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        fail(f"database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, name, status, url, synced_at
            FROM clickup_projects
            ORDER BY name COLLATE NOCASE
            -- LIMIT 1
            """
        ).fetchone()

    if row is None:
        fail("no ClickUp tasks found. Run scripts/connect_clickup.py first.")

    print(json.dumps(dict(row), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
