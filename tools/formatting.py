from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from tools.config import VALID_TAGS


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


def find_project_id_by_name(projects: list[Any], project_name: str) -> str:
    for project in projects:
        if project["name"] == project_name:
            return project["id"]
    return ""


def build_draft_form_state(formatted: dict[str, Any], projects: list[Any]) -> dict[str, str]:
    project_name = str(formatted.get("project_name", "")).strip()
    return {
        "task_id": find_project_id_by_name(projects, project_name),
        "project_name": project_name,
        "progress_text": build_progress_text(formatted),
    }
