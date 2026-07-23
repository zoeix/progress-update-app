from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("CODEX_TIMEOUT_SECONDS", "90"))


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def read_progress_text(args: argparse.Namespace) -> str:
    if args.progress is not None:
        return args.progress
    if args.progress_file is not None:
        return Path(args.progress_file).read_text(encoding="utf-8")
    if args.progress_stdin:
        return sys.stdin.read()
    fail("one of --progress, --progress-file, or --progress-stdin is required")


def post_json(base_url: str, path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"{path} failed: HTTP {exc.code} {detail}")
    except urllib.error.URLError as exc:
        fail(f"{path} failed: {exc}")

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        fail(f"{path} returned non-JSON response: {exc}")
    if not isinstance(parsed, dict):
        fail(f"{path} returned a non-object JSON response")
    return parsed


def find_codex_bin(configured: str) -> str:
    if configured:
        return configured
    env_value = os.environ.get("CODEX_BIN", "").strip()
    if env_value:
        return env_value
    from_path = shutil.which("codex")
    if from_path:
        return from_path
    return "codex"


def run_codex(prompt: str, role: str, run_id: int, args: argparse.Namespace) -> str:
    codex_bin = find_codex_bin(args.codex_bin.strip())
    output_path = Path(tempfile.gettempdir()) / f"progress-update-{role}-{run_id}.json"
    command = [
        codex_bin,
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
    model = (args.codex_model or os.environ.get("CODEX_MODEL", "")).strip()
    if model:
        command[1:1] = ["--model", model]

    try:
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=args.codex_timeout,
            cwd=tempfile.gettempdir(),
            check=False,
        )
    except FileNotFoundError as exc:
        fail(f"codex executable not found: {codex_bin}")
    except subprocess.TimeoutExpired as exc:
        fail(f"codex timed out after {args.codex_timeout} seconds")

    output_text = (
        output_path.read_text(encoding="utf-8")
        if output_path.exists()
        else (result.stdout or result.stderr)
    )
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass

    if result.returncode != 0:
        error = (result.stderr or result.stdout or f"codex exited {result.returncode}").strip()
        fail(f"codex failed: {error}\n\nOutput preview:\n{output_text[:1000]}")
    if not output_text.strip():
        fail("codex returned empty output")
    return output_text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check progress by preparing an app prompt, running Codex, and completing the app update."
    )
    parser.add_argument("--task-id", required=True, help="ClickUp task ID selected from the local app.")
    progress_source = parser.add_mutually_exclusive_group(required=True)
    progress_source.add_argument("--progress", help="Raw progress text.")
    progress_source.add_argument("--progress-file", help="UTF-8 file containing raw progress text.")
    progress_source.add_argument("--progress-stdin", action="store_true", help="Read raw progress text from stdin.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local app base URL.")
    parser.add_argument("--codex-bin", default="", help="Override Codex executable path.")
    parser.add_argument("--codex-model", default="", help="Override Codex model.")
    parser.add_argument("--codex-timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Codex timeout in seconds.")
    parser.add_argument("--http-timeout", type=int, default=30, help="HTTP timeout in seconds.")
    args = parser.parse_args()

    progress_text = read_progress_text(args).strip()
    if not progress_text:
        fail("progress text is required")

    prepare = post_json(
        args.base_url,
        "/api/progress/check/prepare",
        {"task_id": args.task_id, "progress_text": progress_text},
        args.http_timeout,
    )
    prompt = str(prepare.get("prompt_snapshot", "")).strip()
    raw_input = str(prepare.get("raw_input", "")).strip()
    role = str(prepare.get("role", "progress_workflow")).strip() or "progress_workflow"
    try:
        run_id = int(prepare.get("run_id"))
    except (TypeError, ValueError) as exc:
        fail("prepare response did not include a valid run_id")
    if not prompt:
        fail("prepare response did not include prompt_snapshot")
    if not raw_input:
        fail("prepare response did not include raw_input")

    output_text = run_codex(prompt, role, run_id, args)
    complete = post_json(
        args.base_url,
        "/api/progress/check/complete",
        {"run_id": run_id, "raw_input": raw_input, "output_text": output_text},
        args.http_timeout,
    )
    print(json.dumps(complete, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
