from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ALLOWED_KEYS = {"raw_input", "formatted"}
ALLOWED_FORMATTED_KEYS = {
    "project_name",
    "date",
    "this_week_progress",
    "next_week_plan",
    "notes",
}
VALID_TAGS = {"[Risk: Low]", "[Risk: Medium]", "[Risk: High]", "[里程碑]", "[進度]", "[待確認]"}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def validate_items(items: Any, field_name: str) -> None:
    if not isinstance(items, list):
        fail(f"{field_name} must be a list")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            fail(f"{field_name}[{index}] must be an object")
        if set(item) - {"tag", "text"}:
            fail(f"{field_name}[{index}] has unsupported keys")
        tag = str(item.get("tag", "")).strip()
        text = str(item.get("text", "")).strip()
        if tag not in VALID_TAGS:
            fail(f"{field_name}[{index}] has invalid tag")
        if not text:
            fail(f"{field_name}[{index}] text is required")


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        fail("payload must be a JSON object")
    if set(payload) - ALLOWED_KEYS:
        fail("payload may only contain raw_input and formatted")
    formatted = payload.get("formatted")
    if not isinstance(formatted, dict):
        fail("formatted must be a JSON object")
    if set(formatted) - ALLOWED_FORMATTED_KEYS:
        fail("formatted contains unsupported keys")
    validate_items(formatted.get("this_week_progress", []), "this_week_progress")
    validate_items(formatted.get("next_week_plan", []), "next_week_plan")
    notes = formatted.get("notes", [])
    if notes is not None and not isinstance(notes, list):
        fail("notes must be a list")
    return payload


def read_payload_text(args: argparse.Namespace) -> str:
    if args.payload is not None:
        return args.payload
    if args.payload_file is not None:
        return Path(args.payload_file).read_text(encoding="utf-8")
    if args.payload_stdin:
        return sys.stdin.read()
    fail("one of --payload, --payload-file, or --payload-stdin is required")


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a VSCode Codex progress update.")
    payload_source = parser.add_mutually_exclusive_group(required=True)
    payload_source.add_argument("--payload", help="Progress update JSON payload.")
    payload_source.add_argument("--payload-file", help="UTF-8 JSON file containing the progress update payload.")
    payload_source.add_argument("--payload-stdin", action="store_true", help="Read the progress update JSON payload from stdin.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Local app base URL.")
    args = parser.parse_args()

    try:
        payload = validate_payload(json.loads(read_payload_text(args)))
    except json.JSONDecodeError as exc:
        fail(f"payload is not valid JSON: {exc}")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/codex/progress/update",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"progress update failed: HTTP {exc.code} {detail}")
    except urllib.error.URLError as exc:
        fail(f"progress update failed: {exc}")


if __name__ == "__main__":
    main()
