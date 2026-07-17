from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
ENV_PATH = BASE_DIR / ".env"
PROMPTS_DIR = BASE_DIR / "prompts"
load_dotenv(ENV_PATH)

PROMPT_FILES = {
    "format_progress": "format_progress.md",
    "granularity_guidance": "granularity_guidance.md",
    "quality_score": "quality_score.md",
    "question_generation": "question_generation.md",
}
VALID_TAGS = {"[Risk: Low]", "[Risk: Medium]", "[Risk: High]", "[里程碑]", "[進度]", "[待確認]"}
QUESTION_STATUSES = {"resolved", "invalid", "unresolved"}
CODEX_TIMEOUT_SECONDS = int(os.environ.get("CODEX_TIMEOUT_SECONDS", "90"))
CODEX_MODEL = os.environ.get("CODEX_MODEL", "").strip()
CLICKUP_API_BASE = "https://api.clickup.com/api/v2"
CLICKUP_PAGE_SIZE = 100

STATE_EDITING = "editing_progress"
STATE_NEEDS_MORE_INFO = "needs_more_info"
STATE_READY_FOR_REVIEW = "ready_for_review"

app = FastAPI(title="Progress Update App")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
clickup_session_active = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_prompt(name: str) -> str:
    filename = PROMPT_FILES[name]
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def load_prompts() -> dict[str, str]:
    return {name: load_prompt(name) for name in PROMPT_FILES}


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


@app.on_event("startup")
def on_startup() -> None:
    init_db()


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


def get_latest_questions_for_session(conn: sqlite3.Connection, session_id: int) -> list[sqlite3.Row]:
    latest_entry = get_latest_entry(conn, session_id)
    return get_questions(conn, latest_entry["id"] if latest_entry else None)


def serialize_previous_questions(questions: list[sqlite3.Row]) -> list[dict[str, str]]:
    previous_questions = []
    for question in questions:
        previous_questions.append(
            {
                "id": str(question["id"]),
                "target_field": question["target_field"],
                "question": question["question"],
                "reason": question["reason"],
                "priority": question["priority"],
                "status": question["status"] if "status" in question.keys() else "unresolved",
            }
        )
    return previous_questions


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


def extract_json_object(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1).strip())

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(stripped[start : end + 1])

    preview = stripped[:500] if stripped else "(empty output)"
    raise ValueError(f"Codex output did not contain valid JSON. Output preview: {preview}")


def create_codex_run(session_id: int, role: str, prompt_snapshot: str) -> int:
    now = utc_now()
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO codex_runs (
                session_id, role, prompt_snapshot, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, role, prompt_snapshot, "running", now, now),
        )
        return cursor.lastrowid


def finish_codex_run(
    run_id: int,
    status: str,
    output_text: str = "",
    output_json: Any | None = None,
    error: str | None = None,
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE codex_runs
            SET status = ?, output_text = ?, output_json = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                output_text,
                json.dumps(output_json, ensure_ascii=False) if output_json is not None else "",
                error,
                utc_now(),
                run_id,
            ),
        )


def run_codex_json(session_id: int, role: str, prompt_snapshot: str) -> Any:
    run_id = create_codex_run(session_id, role, prompt_snapshot)
    output_path = Path(tempfile.gettempdir()) / f"progress-update-{role}-{run_id}.json"
    run_finished = False
    output_text = ""
    command = [
        get_codex_bin(),
        "--config",
        "service_tier=fast",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(output_path),
        "-",
    ]
    if CODEX_MODEL:
        command[2:2] = ["--model", CODEX_MODEL]
    try:
        result = subprocess.run(
            command,
            input=prompt_snapshot,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=CODEX_TIMEOUT_SECONDS,
            cwd=tempfile.gettempdir(),
            check=False,
        )
        output_text = output_path.read_text(encoding="utf-8") if output_path.exists() else (result.stdout or result.stderr)
        if result.returncode != 0:
            error = (result.stderr or result.stdout or f"codex exited {result.returncode}").strip()
            finish_codex_run(run_id, "error", output_text, error=error)
            run_finished = True
            raise RuntimeError(error)

        output_json = extract_json_object(output_text)
        finish_codex_run(run_id, "success", output_text, output_json)
        run_finished = True
        return output_json
    except subprocess.TimeoutExpired as exc:
        if not run_finished:
            finish_codex_run(run_id, "timeout", output_text, error=str(exc))
        raise
    except Exception as exc:
        if not run_finished:
            finish_codex_run(run_id, "error", output_text, error=str(exc))
        raise
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def today_label() -> str:
    return datetime.now().strftime("%Y/%m/%d")


def split_tagged_item(item: str) -> tuple[str, str]:
    match = re.match(r"^\s*(\[[^\]]+\])\s*(.+)$", item)
    if match:
        tag = match.group(1).strip()
        text = match.group(2).strip()
        return tag, text
    return "", item.strip()


def item_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text", "")).strip()
    return str(item).strip()


def item_tag(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("tag", "")).strip()
    tag, _ = split_tagged_item(str(item))
    return tag


def normalize_items(items: list[Any]) -> list[dict[str, str]]:
    if not isinstance(items, list):
        raise ValueError("progress items must be a list")
    normalized = []
    for index, item in enumerate(items, start=1):
        text = item_text(item)
        if not text or text == "待補":
            continue
        tag = item_tag(item)
        if tag not in VALID_TAGS:
            raise ValueError(f"item {index} has invalid or missing tag")
        normalized.append({"tag": tag, "text": text})
    return normalized


def numbered(items: list[Any]) -> str:
    items = normalize_items(items)
    if not items:
        return "1. 待補"
    return "\n".join(f"{index}. {item['tag']} {item['text']}" for index, item in enumerate(items, start=1))


def render_final_text(formatted: dict[str, Any]) -> str:
    lines = []
    if formatted["project_name"]:
        lines.append(f"專案名稱: {formatted['project_name']}")
        lines.append("")
    lines.append("# 本週進度：")
    lines.append(numbered(formatted["this_week_progress"]))
    lines.append("")
    lines.append("# 下週進度：")
    lines.append(numbered(formatted["next_week_plan"]))
    return "\n".join(lines)


def build_progress_workflow_prompt(
    raw_input: str,
    previous_questions: list[dict[str, str]],
    prompts: dict[str, str],
) -> str:
    return f"""
你是本機週報整理流程的整合處理器。請一次完成格式化、品質評分、問題狀態檢視與追問產生，並只回傳 JSON。

請依序套用下列規則，但最後只輸出一個 JSON 物件。

## 格式化規則

{prompts["format_progress"]}

## 品質評分規則

{prompts["quality_score"]}

## 問題追問與狀態判斷規則

{prompts["question_generation"]}

## 內容顆粒度規範

{prompts["granularity_guidance"]}

## 輸出格式

請只回傳下列 JSON 結構，不要輸出 Markdown 或說明文字：

{{
  "formatted": {{
    "project_name": "",
    "this_week_progress": [
      {{"tag": "[進度]", "text": ""}}
    ],
    "next_week_plan": [
      {{"tag": "[待確認]", "text": ""}}
    ],
    "notes": []
  }},
  "evaluation": {{
    "score": 0,
    "subscores": [
      {{"name": "背景", "score": 0, "max_score": 15}},
      {{"name": "目前狀態", "score": 0, "max_score": 30}},
      {{"name": "下週計畫", "score": 0, "max_score": 20}},
      {{"name": "健康度", "score": 0, "max_score": 20}},
      {{"name": "風險 / Tag", "score": 0, "max_score": 15}}
    ],
    "missing_fields": [],
    "strengths": [],
    "ready_for_review": false
  }},
  "question_result": {{
    "question_reviews": [
      {{
        "previous_question_id": "1",
        "status": "resolved",
        "reason": ""
      }}
    ],
    "questions": [
      {{
        "id": "q1",
        "status": "unresolved",
        "target_field": "this_week_progress",
        "question": "",
        "reason": "",
        "priority": "high",
        "previous_question_id": ""
      }}
    ]
  }}
}}

## 使用者週報草稿

{raw_input}

## 上一輪問題清單

{json.dumps(previous_questions, ensure_ascii=False, indent=2)}
""".strip()


def validate_formatted_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("formatted output must be an object")
    formatted = {
        "project_name": str(value.get("project_name", "")).strip(),
        "date": str(value.get("date", "")).strip() or today_label(),
        "this_week_progress": normalize_items(value.get("this_week_progress", [])),
        "next_week_plan": normalize_items(value.get("next_week_plan", [])),
        "notes": value.get("notes", []) if isinstance(value.get("notes", []), list) else [],
    }
    return formatted


def validate_evaluation_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("evaluation output must be an object")
    score = value.get("score", 0)
    if not isinstance(score, int):
        score = int(score) if str(score).isdigit() else 0
    missing_fields = value.get("missing_fields", [])
    strengths = value.get("strengths", [])
    raw_subscores = value.get("subscores", [])
    subscores = []
    if isinstance(raw_subscores, list):
        for item in raw_subscores:
            if not isinstance(item, dict):
                continue
            subscore = item.get("score", 0)
            max_score = item.get("max_score", 0)
            if not isinstance(subscore, int):
                subscore = int(subscore) if str(subscore).isdigit() else 0
            if not isinstance(max_score, int):
                max_score = int(max_score) if str(max_score).isdigit() else 0
            subscores.append(
                {
                    "name": str(item.get("name", "")).strip(),
                    "score": max(0, subscore),
                    "max_score": max(0, max_score),
                }
            )
    return {
        "score": max(0, min(100, score)),
        "subscores": [item for item in subscores if item["name"]],
        "missing_fields": missing_fields if isinstance(missing_fields, list) else [],
        "strengths": strengths if isinstance(strengths, list) else [],
        "ready_for_review": bool(value.get("ready_for_review", False)),
    }


def normalize_question_status(status: Any) -> str:
    clean_status = str(status or "unresolved").strip()
    return clean_status if clean_status in QUESTION_STATUSES else "unresolved"


def validate_questions_json(value: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict):
        raise ValueError("question output must be an object")
    raw_reviews = value.get("question_reviews", [])
    if not isinstance(raw_reviews, list):
        raw_reviews = []
    question_reviews = []
    for item in raw_reviews:
        if not isinstance(item, dict):
            continue
        previous_question_id = str(item.get("previous_question_id", "")).strip()
        if not previous_question_id:
            continue
        question_reviews.append(
            {
                "previous_question_id": previous_question_id,
                "status": normalize_question_status(item.get("status")),
                "reason": str(item.get("reason", "")).strip(),
            }
        )

    raw_questions = value.get("questions", [])
    if not isinstance(raw_questions, list):
        raise ValueError("questions must be a list")
    questions = []
    for index, item in enumerate(raw_questions[:3], start=1):
        if not isinstance(item, dict):
            continue
        target_field = str(item.get("target_field", "notes"))
        if target_field not in {"project_name", "this_week_progress", "next_week_plan", "notes"}:
            target_field = "notes"
        questions.append(
            {
                "id": str(item.get("id") or f"q{index}"),
                "status": "unresolved",
                "target_field": target_field,
                "question": str(item.get("question", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "priority": str(item.get("priority", "medium")).strip() or "medium",
                "previous_question_id": str(item.get("previous_question_id", "")).strip(),
            }
        )
    return {
        "question_reviews": question_reviews,
        "questions": [question for question in questions if question["question"]],
    }


def validate_progress_workflow_json(
    value: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, str]]]]:
    if not isinstance(value, dict):
        raise ValueError("progress workflow output must be an object")
    formatted = validate_formatted_json(value.get("formatted"))
    evaluation = validate_evaluation_json(value.get("evaluation"))
    question_result = validate_questions_json(value.get("question_result"))
    return formatted, evaluation, question_result


def refine_progress_with_codex(
    session_id: int,
    raw_input: str,
    previous_questions: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, str]]], str]:
    prompts = load_prompts()
    formatted, evaluation, question_result = validate_progress_workflow_json(
        run_codex_json(
            session_id,
            "progress_workflow",
            build_progress_workflow_prompt(raw_input, previous_questions, prompts),
        )
    )
    final_text = render_final_text(formatted)
    return formatted, evaluation, question_result, final_text


def refine_progress(
    raw_input: str,
    session_id: int,
    previous_questions: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, str]]], str]:
    return refine_progress_with_codex(session_id, raw_input, previous_questions)


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
    for review in question_result["question_reviews"]:
        conn.execute(
            """
            UPDATE questions
            SET status = ?, review_reason = ?
            WHERE id = ? AND session_id = ?
            """,
            (
                review["status"],
                review["reason"],
                review["previous_question_id"],
                session_id,
            ),
        )
    for question in questions:
        conn.execute(
            """
            INSERT INTO questions (
                session_id, entry_id, question, reason, priority,
                target_field, status, review_reason, previous_question_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                entry_id,
                question["question"],
                question["reason"],
                question["priority"],
                question["target_field"],
                question["status"],
                "",
                question["previous_question_id"],
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


def items_to_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    lines = []
    for item in items:
        if isinstance(item, dict):
            tag = str(item.get("tag", "")).strip()
            text = str(item.get("text", "")).strip()
            line = f"{tag} {text}".strip()
        else:
            line = str(item).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def build_progress_text(formatted: dict[str, Any]) -> str:
    this_week = normalize_items(formatted.get("this_week_progress", []))
    next_week = normalize_items(formatted.get("next_week_plan", []))
    if not this_week and not next_week:
        return ""
    return "\n\n".join(
        [
            "# 本週進度：\n" + "\n".join(
                f"{index}. {item['tag']} {item['text']}" for index, item in enumerate(this_week, start=1)
            ),
            "# 下週進度：\n" + "\n".join(
                f"{index}. {item['tag']} {item['text']}" for index, item in enumerate(next_week, start=1)
            ),
        ]
    ).strip()


def build_progress_input(project_name: str, progress_text: str) -> str:
    return "\n".join(
        [
            f"專案名稱: {project_name.strip()}",
            progress_text.strip(),
        ]
    ).strip()


def build_clickup_upload_content(progress_text: str) -> str:
    return progress_text.strip()


def find_project_id_by_name(projects: list[sqlite3.Row], project_name: str) -> str:
    for project in projects:
        if project["name"] == project_name:
            return project["id"]
    return ""


def build_draft_form_state(formatted: dict[str, Any], projects: list[sqlite3.Row]) -> dict[str, str]:
    project_name = str(formatted.get("project_name", "")).strip()
    return {
        "task_id": find_project_id_by_name(projects, project_name),
        "project_name": project_name,
        "progress_text": build_progress_text(formatted),
    }


def build_codex_direct_evaluation() -> dict[str, Any]:
    return {
        "score": 100,
        "subscores": [],
        "missing_fields": [],
        "strengths": ["由 VSCode Codex 依進度格式規則直接更新。"],
        "ready_for_review": True,
    }


def build_empty_question_result() -> dict[str, list[dict[str, str]]]:
    return {"question_reviews": [], "questions": []}


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


def stop_server_process() -> None:
    threading.Timer(0.5, lambda: os._exit(0)).start()


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "clickup_token": get_clickup_token(),
            "clickup_list_id": get_clickup_list_id(),
            "codex_bin": find_codex_bin(),
            "error": "",
            "project_count": None,
        },
    )


@app.post("/login")
def save_login(
    request: Request,
    clickup_token: str = Form(...),
    clickup_list_id: str = Form(...),
    codex_bin: str = Form(""),
):
    global clickup_session_active
    clean_token = clickup_token.strip()
    clean_list_id = clickup_list_id.strip()
    clean_codex_bin = codex_bin.strip()
    if not clean_token or not clean_list_id:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "clickup_token": clean_token,
                "clickup_list_id": clean_list_id,
                "codex_bin": clean_codex_bin,
                "error": "請輸入 CLICKUP_TOKEN 與 CLICKUP_LIST_ID。",
                "project_count": None,
            },
            status_code=400,
        )

    try:
        projects = fetch_clickup_projects(clean_token, clean_list_id)
    except Exception as exc:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "clickup_token": clean_token,
                "clickup_list_id": clean_list_id,
                "codex_bin": clean_codex_bin,
                "error": f"ClickUp 連線失敗：{exc}",
                "project_count": None,
            },
            status_code=400,
        )

    save_clickup_config(clean_token, clean_list_id, clean_codex_bin)
    clickup_session_active = True
    with get_db() as conn:
        save_clickup_projects(conn, projects)
    return RedirectResponse("/", status_code=303)


@app.get("/")
def home(request: Request):
    if not has_clickup_config():
        return RedirectResponse("/login", status_code=303)
    with get_db() as conn:
        session = get_session(conn)
        latest_entry = get_latest_entry(conn, session["id"])
        questions = get_questions(conn, latest_entry["id"] if latest_entry else None)
        project_count = get_clickup_project_count(conn)
        projects = get_clickup_projects(conn)
        formatted = parse_json_field(latest_entry, "formatted_json", {})
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "session": session,
                "entry": latest_entry,
                "formatted": formatted,
                "form_state": build_draft_form_state(formatted, projects),
                "evaluation": parse_json_field(latest_entry, "evaluation_json", {}),
                "questions": questions,
                "project_count": project_count,
                "projects": projects,
                "today": today_label(),
            },
        )


@app.post("/reset")
def reset_progress():
    if not has_clickup_config():
        return RedirectResponse("/login", status_code=303)
    with get_db() as conn:
        reset_progress_data(conn)
    return RedirectResponse("/", status_code=303)


@app.post("/finish")
def finish_progress():
    global clickup_session_active
    with get_db() as conn:
        reset_progress_data(conn)
    clickup_session_active = False
    stop_server_process()
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="zh-Hant">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>服務已結束</title>
          </head>
          <body>
            <main style="font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 48px auto; color: #1f2328;">
              <h1 style="font-size: 24px;">服務已結束</h1>
              <p>目前進度資料已重設，服務正在關閉。</p>
            </main>
          </body>
        </html>
        """
    )


@app.get("/codex/progress/current")
def codex_progress_current():
    with get_db() as conn:
        return serialize_latest_progress(conn)


@app.post("/codex/progress/update")
async def codex_progress_update(request: Request):
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    raw_formatted = payload.get("formatted", payload)
    try:
        formatted = validate_formatted_json(raw_formatted)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    final_text = render_final_text(formatted)
    raw_input = str(payload.get("raw_input", "")).strip() or final_text
    now = utc_now()
    evaluation = build_codex_direct_evaluation()
    question_result = build_empty_question_result()

    with get_db() as conn:
        session_id = get_session(conn)["id"]
        entry_id = save_refinement(
            conn,
            session_id,
            raw_input,
            formatted,
            evaluation,
            question_result,
            final_text,
            now,
        )
        set_session_notice(conn, session_id, "已由 VSCode Codex 更新進度。")

    return {
        "ok": True,
        "entry_id": entry_id,
        "final_text": final_text,
        "formatted": formatted,
    }


@app.post("/progress")
def submit_progress(
    task_id: str = Form(...),
    progress_text: str = Form(...),
):
    if not has_clickup_config():
        return RedirectResponse("/login", status_code=303)
    with get_db() as conn:
        project = get_clickup_project(conn, task_id)
        if project is None:
            session_id = get_session(conn)["id"]
            set_session_error(conn, session_id, "找不到選擇的 ClickUp 專案，請重新同步或重新選擇。")
            return RedirectResponse("/", status_code=303)
        project_name = project["name"]
    clean_text = build_progress_input(project_name, progress_text)
    if not clean_text:
        return RedirectResponse("/", status_code=303)

    now = utc_now()
    with get_db() as conn:
        session_id = get_session(conn)["id"]
        previous_questions = serialize_previous_questions(get_latest_questions_for_session(conn, session_id))

    try:
        formatted, evaluation, question_result, final_text = refine_progress(
            clean_text,
            session_id,
            previous_questions,
        )
    except Exception as exc:
        with get_db() as conn:
            set_session_error(conn, session_id, f"Codex workflow failed: {exc}")
        return RedirectResponse("/", status_code=303)

    with get_db() as conn:
        save_refinement(conn, session_id, clean_text, formatted, evaluation, question_result, final_text, now)

    return RedirectResponse("/", status_code=303)


@app.post("/draft")
def refine_draft(
    task_id: str = Form(...),
    progress_text: str = Form(...),
):
    if not has_clickup_config():
        return RedirectResponse("/login", status_code=303)
    with get_db() as conn:
        project = get_clickup_project(conn, task_id)
        if project is None:
            session_id = get_session(conn)["id"]
            set_session_error(conn, session_id, "找不到選擇的 ClickUp 專案，請重新同步或重新選擇。")
            return RedirectResponse("/", status_code=303)
        project_name = project["name"]
    clean_text = build_progress_input(project_name, progress_text)
    if not clean_text:
        return RedirectResponse("/", status_code=303)

    now = utc_now()
    with get_db() as conn:
        session_id = get_session(conn)["id"]
        previous_questions = serialize_previous_questions(get_latest_questions_for_session(conn, session_id))

    try:
        formatted, evaluation, question_result, final_text = refine_progress(
            clean_text,
            session_id,
            previous_questions,
        )
    except Exception as exc:
        with get_db() as conn:
            set_session_error(conn, session_id, f"Codex workflow failed: {exc}")
        return RedirectResponse("/", status_code=303)

    with get_db() as conn:
        save_refinement(conn, session_id, clean_text, formatted, evaluation, question_result, final_text, now)

    return RedirectResponse("/", status_code=303)


@app.post("/upload")
def upload_progress(
    task_id: str = Form(...),
    progress_text: str = Form(...),
):
    if not has_clickup_config():
        return RedirectResponse("/login", status_code=303)
    with get_db() as conn:
        session_id = get_session(conn)["id"]
        project = get_clickup_project(conn, task_id)
        if project is None:
            set_session_error(conn, session_id, "找不到選擇的 ClickUp 專案，請重新同步或重新選擇。")
            return RedirectResponse("/", status_code=303)
        content = build_clickup_upload_content(progress_text)

    try:
        post_clickup_comment(task_id, content)
    except Exception as exc:
        with get_db() as conn:
            set_session_error(conn, session_id, f"ClickUp 上傳失敗：{exc}")
        return RedirectResponse("/", status_code=303)

    with get_db() as conn:
        set_session_error(conn, session_id, None)
        set_session_notice(conn, session_id, f"已上傳進度到 ClickUp：{project['name']}")
    return RedirectResponse("/", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
