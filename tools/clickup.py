from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import httpx
from dotenv import set_key

from tools.config import CLICKUP_API_BASE, CLICKUP_PAGE_SIZE, ENV_PATH, utc_now
from tools.db import get_db


clickup_session_active = False


def set_clickup_session_active(active: bool) -> None:
    global clickup_session_active
    clickup_session_active = active


def get_clickup_token() -> str:
    return os.environ.get("CLICKUP_TOKEN", "").strip()


def get_clickup_list_id() -> str:
    return os.environ.get("CLICKUP_LIST_ID", "").strip()


def find_codex_bin() -> str:
    configured = os.environ.get("CODEX_BIN", "").strip()
    if configured:
        return configured

    from_path = shutil.which("codex")
    if from_path:
        return from_path

    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "npm" / "codex.cmd")
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        candidates.append(Path(local_appdata) / "npm" / "codex.cmd")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return ""


def get_codex_bin() -> str:
    return find_codex_bin() or "codex"


def has_clickup_config() -> bool:
    return clickup_session_active and bool(get_clickup_token() and get_clickup_list_id())


def fetch_clickup_projects(clickup_token: str, clickup_list_id: str) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    headers = {"Authorization": clickup_token}
    with httpx.Client(timeout=30) as client:
        page = 0
        while True:
            response = client.get(
                f"{CLICKUP_API_BASE}/list/{clickup_list_id}/task",
                headers=headers,
                params={
                    "page": page,
                    "include_closed": "true",
                    "subtasks": "true",
                },
            )
            if response.status_code == 401:
                raise ValueError("ClickUp token 無效或沒有權限。")
            if response.status_code == 404:
                raise ValueError("找不到 ClickUp List，請確認 CLICKUP_LIST_ID。")
            response.raise_for_status()
            tasks = response.json().get("tasks", [])
            if not isinstance(tasks, list):
                raise ValueError("ClickUp 回傳格式不符合預期。")
            projects.extend(tasks)
            if len(tasks) < CLICKUP_PAGE_SIZE:
                break
            page += 1
    return projects


def save_clickup_projects(conn: sqlite3.Connection, projects: list[dict[str, Any]]) -> None:
    now = utc_now()
    conn.execute("DELETE FROM clickup_projects")
    for project in projects:
        project_id = str(project.get("id", "")).strip()
        if not project_id:
            continue
        status = project.get("status", {})
        status_name = status.get("status", "") if isinstance(status, dict) else ""
        conn.execute(
            """
            INSERT OR REPLACE INTO clickup_projects (
                id, name, status, url, raw_json, synced_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                str(project.get("name", "")).strip() or "(未命名專案)",
                str(status_name).strip(),
                str(project.get("url", "")).strip(),
                json.dumps(project, ensure_ascii=False),
                now,
            ),
        )


def get_clickup_project_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM clickup_projects").fetchone()[0]


def get_clickup_projects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, name, status, url
        FROM clickup_projects
        ORDER BY name COLLATE NOCASE
        """
    ).fetchall()


def get_clickup_project(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, name, status, url
        FROM clickup_projects
        WHERE id = ?
        """,
        (task_id,),
    ).fetchone()


def post_clickup_comment(task_id: str, content: str) -> None:
    token = get_clickup_token()
    if not token:
        raise ValueError("找不到 CLICKUP_TOKEN，請重新設定 ClickUp 連線。")
    response = httpx.post(
        f"{CLICKUP_API_BASE}/task/{task_id}/comment",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": token,
        },
        json={
            "notify_all": False,
            "comment_text": content,
        },
        timeout=30,
    )
    if response.status_code == 401:
        raise ValueError("ClickUp token 無效或沒有權限。")
    if response.status_code == 404:
        raise ValueError("找不到 ClickUp task，請重新同步專案清單。")
    response.raise_for_status()


def save_clickup_config(clickup_token: str, clickup_list_id: str, codex_bin: str = "") -> None:
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), "CLICKUP_TOKEN", clickup_token)
    set_key(str(ENV_PATH), "CLICKUP_LIST_ID", clickup_list_id)
    set_key(str(ENV_PATH), "CODEX_BIN", codex_bin)
    os.environ["CLICKUP_TOKEN"] = clickup_token
    os.environ["CLICKUP_LIST_ID"] = clickup_list_id
    os.environ["CODEX_BIN"] = codex_bin


def connect_clickup(clickup_token: str, clickup_list_id: str, codex_bin: str = "") -> int:
    clean_token = clickup_token.strip()
    clean_list_id = clickup_list_id.strip()
    clean_codex_bin = codex_bin.strip()
    if not clean_token or not clean_list_id:
        raise ValueError("請輸入 CLICKUP_TOKEN 與 CLICKUP_LIST_ID。")

    projects = fetch_clickup_projects(clean_token, clean_list_id)
    save_clickup_config(clean_token, clean_list_id, clean_codex_bin)
    with get_db() as conn:
        save_clickup_projects(conn, projects)
    return len(projects)
