from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.clickup import get_codex_bin
from tools.config import CODEX_MODEL, CODEX_TIMEOUT_SECONDS, utc_now
from tools.db import get_db


@dataclass(frozen=True)
class CodexRunSpec:
    session_id: int
    role: str
    prompt_snapshot: str


class CodexCliError(RuntimeError):
    def __init__(self, message: str, output_text: str):
        super().__init__(message)
        self.output_text = output_text


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


def get_codex_run(conn, run_id: int):
    return conn.execute(
        """
        SELECT *
        FROM codex_runs
        WHERE id = ?
        """,
        (run_id,),
    ).fetchone()


def prepare_codex_run(session_id: int, role: str, prompt_snapshot: str) -> CodexRunSpec:
    return CodexRunSpec(session_id=session_id, role=role, prompt_snapshot=prompt_snapshot)


def run_codex_cli(run_id: int, role: str, prompt_snapshot: str) -> str:
    output_path = Path(tempfile.gettempdir()) / f"progress-update-{role}-{run_id}.json"
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
        output_text = (
            output_path.read_text(encoding="utf-8")
            if output_path.exists()
            else (result.stdout or result.stderr)
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or f"codex exited {result.returncode}").strip()
            raise CodexCliError(error, output_text)
        return output_text
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def complete_codex_json_run(run_id: int, output_text: str) -> Any:
    output_json = extract_json_object(output_text)
    finish_codex_run(run_id, "success", output_text, output_json)
    return output_json


def run_codex_json_with_run_id(session_id: int, role: str, prompt_snapshot: str) -> tuple[Any, int]:
    spec = prepare_codex_run(session_id, role, prompt_snapshot)
    run_id = create_codex_run(spec.session_id, spec.role, spec.prompt_snapshot)
    output_text = ""
    run_finished = False
    try:
        output_text = run_codex_cli(run_id, spec.role, spec.prompt_snapshot)
        output_json = complete_codex_json_run(run_id, output_text)
        run_finished = True
        return output_json, run_id
    except CodexCliError as exc:
        output_text = exc.output_text
        finish_codex_run(run_id, "error", output_text, error=str(exc))
        run_finished = True
        raise
    except subprocess.TimeoutExpired as exc:
        if not run_finished:
            finish_codex_run(run_id, "timeout", output_text, error=str(exc))
        raise
    except Exception as exc:
        if not run_finished:
            finish_codex_run(run_id, "error", output_text, error=str(exc))
        raise


def run_codex_json(session_id: int, role: str, prompt_snapshot: str) -> Any:
    output_json, _run_id = run_codex_json_with_run_id(session_id, role, prompt_snapshot)
    return output_json
