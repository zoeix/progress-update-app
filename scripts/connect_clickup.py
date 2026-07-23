from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app import connect_clickup, find_codex_bin, get_clickup_list_id, get_clickup_token, init_db


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect the local app to ClickUp using app.connect_clickup().")
    parser.add_argument("--clickup-token", default="", help="Override CLICKUP_TOKEN from the environment.")
    parser.add_argument("--clickup-list-id", default="", help="Override CLICKUP_LIST_ID from the environment.")
    parser.add_argument("--codex-bin", default="", help="Override CODEX_BIN from the environment.")
    args = parser.parse_args()

    clickup_token = (args.clickup_token or get_clickup_token()).strip()
    clickup_list_id = (args.clickup_list_id or get_clickup_list_id()).strip()
    codex_bin = (args.codex_bin or os.environ.get("CODEX_BIN", "").strip() or find_codex_bin()).strip()

    try:
        init_db()
        project_count = connect_clickup(clickup_token, clickup_list_id, codex_bin)
    except Exception as exc:
        fail(f"ClickUp connect failed: {exc}")

    print(
        json.dumps(
            {
                "ok": True,
                "message": "ClickUp 連線成功，已同步專案清單。",
                "project_count": project_count,
                "clickup_list_id": clickup_list_id,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
