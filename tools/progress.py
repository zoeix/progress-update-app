from __future__ import annotations

import json
import time
from typing import Any

from tools.clickup import get_clickup_project, has_clickup_config
from tools.codex import (
    create_codex_run,
    extract_json_object,
    finish_codex_run,
    get_codex_run,
    prepare_codex_run,
    run_codex_json_with_run_id,
)
from tools.config import BASE_DIR, PROMPT_FILES, PROMPTS_DIR, utc_now
from tools.db import get_db, get_session, keep_only_latest_progress, save_refinement, set_session_error
from tools.formatting import build_progress_input, normalize_items, render_final_text, today_label

BRIDGE_DIR = BASE_DIR / "bridge"
BRIDGE_PROMPT_PATH = BRIDGE_DIR / "prompt.md"
BRIDGE_RESPONSE_PATH = BRIDGE_DIR / "res.json"
BRIDGE_POLL_SECONDS = 0.5


def load_prompt(name: str) -> str:
    filename = PROMPT_FILES[name]
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def load_prompts() -> dict[str, str]:
    return {name: load_prompt(name) for name in PROMPT_FILES}


def build_progress_workflow_prompt(
    raw_input: str,
    prompts: dict[str, str],
) -> str:
    return f"""
你是本機週報整理流程的整合處理器。請一次完成格式化、品質評分與追問產生，並只回傳 JSON。

請依序套用下列規則，但最後只輸出一個 JSON 物件。

## 格式化規則

{prompts["formatted"]}

## 品質評分規則

{prompts["evaluation"]}

## 問題追問方式

{prompts["question_result"]}


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
    "summary_sentences": [
      "整體評分判斷。",
      "主要優點。",
      "最需要補強的地方。"
    ],
    "subscores": [
      {{"name": "完整度", "score": 0, "max_score": 10}},
      {{"name": "顆粒度", "score": 0, "max_score": 20}},
      {{"name": "支持度", "score": 0, "max_score": 30}},
      {{"name": "解釋性", "score": 0, "max_score": 20}},
      {{"name": "計劃性", "score": 0, "max_score": 20}}
    ],
    "missing_fields": [],
    "strengths": [],
    "ready_for_review": false
  }},
  "question_result": {{
    "questions": [
      {{
        "id": "q1",
        "type": "question",
        "tag": "完整度",
        "target_field": "this_week_progress",
        "question": "",
        "example": "",
        "priority": "high"
      }}
    ]
  }}
}}

## 使用者週報草稿

{raw_input}

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
    summary_sentences = value.get("summary_sentences", [])
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
        "summary_sentences": [
            str(item).strip() for item in summary_sentences[:3]
            if str(item).strip()
        ] if isinstance(summary_sentences, list) else [],
        "subscores": [item for item in subscores if item["name"]],
        "missing_fields": missing_fields if isinstance(missing_fields, list) else [],
        "strengths": strengths if isinstance(strengths, list) else [],
        "ready_for_review": bool(value.get("ready_for_review", False)),
    }


def validate_questions_json(value: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict):
        raise ValueError("question output must be an object")
    raw_questions = value.get("questions", [])
    if not isinstance(raw_questions, list):
        raise ValueError("questions must be a list")
    questions = []
    valid_tags = {"完整度", "顆粒度", "支持度", "解釋性", "計劃性"}
    for index, item in enumerate(raw_questions[:5], start=1):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "question")).strip()
        if item_type not in {"question", "suggestion"}:
            item_type = "question"
        tag = str(item.get("tag", "")).strip()
        if tag not in valid_tags:
            tag = "完整度"
        target_field = str(item.get("target_field", "notes"))
        if target_field not in {"project_name", "this_week_progress", "next_week_plan", "notes"}:
            target_field = "notes"
        example = str(item.get("example", item.get("reason", ""))).strip()
        questions.append(
            {
                "id": str(item.get("id") or f"q{index}"),
                "type": item_type,
                "tag": tag,
                "target_field": target_field,
                "question": str(item.get("question", "")).strip(),
                "reason": example,
                "priority": str(item.get("priority", "medium")).strip() or "medium",
            }
        )
    return {
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
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, str]]], str, int]:
    prompts = load_prompts()
    spec = prepare_codex_run(
        session_id,
        "progress_workflow",
        build_progress_workflow_prompt(raw_input, prompts),
    )
    output_json, run_id = run_codex_json_with_run_id(
        spec.session_id,
        spec.role,
        spec.prompt_snapshot,
    )
    formatted, evaluation, question_result = validate_progress_workflow_json(
        output_json
    )
    final_text = render_final_text(formatted)
    return formatted, evaluation, question_result, final_text, run_id


def refine_progress(
    raw_input: str,
    session_id: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, str]]], str, int]:
    return refine_progress_with_codex(session_id, raw_input)


def prepare_progress_check(task_id: str, progress_text: str) -> dict[str, Any]:
    if not has_clickup_config():
        raise ValueError("尚未設定 ClickUp 連線。")
    with get_db() as conn:
        project = get_clickup_project(conn, task_id)
        session_id = get_session(conn)["id"]
        if project is None:
            set_session_error(conn, session_id, "找不到選擇的 ClickUp 專案，請重新同步或重新選擇。")
            raise ValueError("找不到選擇的 ClickUp 專案，請重新同步或重新選擇。")
        project_name = project["name"]

    raw_input = build_progress_input(project_name, progress_text)
    if not raw_input:
        raise ValueError("請輸入進度內容。")

    spec = prepare_codex_run(
        session_id,
        "progress_workflow",
        build_progress_workflow_prompt(raw_input, load_prompts()),
    )
    run_id = create_codex_run(spec.session_id, spec.role, spec.prompt_snapshot)
    return {
        "ok": True,
        "run_id": run_id,
        "session_id": spec.session_id,
        "role": spec.role,
        "raw_input": raw_input,
        "prompt_snapshot": spec.prompt_snapshot,
    }


def complete_progress_check(run_id: int, raw_input: str, output: Any) -> dict[str, Any]:
    clean_input = raw_input.strip()
    if not clean_input:
        raise ValueError("raw_input is required")

    output_text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    try:
        output_json = extract_json_object(output_text) if isinstance(output, str) else output
        formatted, evaluation, question_result = validate_progress_workflow_json(output_json)
        final_text = render_final_text(formatted)
    except Exception as exc:
        finish_codex_run(run_id, "error", output_text, error=str(exc))
        raise

    with get_db() as conn:
        run = get_codex_run(conn, run_id)
        if run is None:
            raise ValueError("codex run not found")
        if run["role"] != "progress_workflow":
            raise ValueError("codex run role does not match progress workflow")
        session_id = run["session_id"]
        entry_id = save_refinement(
            conn,
            session_id,
            clean_input,
            formatted,
            evaluation,
            question_result,
            final_text,
            utc_now(),
        )
        keep_only_latest_progress(conn, session_id, entry_id, run_id)
    finish_codex_run(run_id, "success", output_text, output_json)

    return {
        "ok": True,
        "entry_id": entry_id,
        "run_id": run_id,
        "raw_input": clean_input,
        "formatted": formatted,
        "evaluation": evaluation,
        "question_result": question_result,
        "final_text": final_text,
    }


def wait_for_bridge_response(timeout: int | None = None) -> str:
    started_at = time.monotonic()
    last_error = ""

    while True:
        if BRIDGE_RESPONSE_PATH.exists():
            try:
                output_text = BRIDGE_RESPONSE_PATH.read_text(encoding="utf-8")
                extract_json_object(output_text)
                return output_text
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)

        if timeout is not None and time.monotonic() - started_at >= timeout:
            detail = f" Last parse error: {last_error}" if last_error else ""
            raise TimeoutError(f"Timed out waiting for {BRIDGE_RESPONSE_PATH}.{detail}")

        time.sleep(BRIDGE_POLL_SECONDS)


def check_progress_update_with_bridge(task_id: str, progress_text: str) -> dict[str, Any]:
    prepared = prepare_progress_check(task_id, progress_text)
    run_id = int(prepared["run_id"])
    prompt_snapshot = str(prepared["prompt_snapshot"])
    raw_input = str(prepared["raw_input"])

    try:
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        BRIDGE_RESPONSE_PATH.unlink(missing_ok=True)
        BRIDGE_PROMPT_PATH.write_text(prompt_snapshot, encoding="utf-8")
        output_text = wait_for_bridge_response()
    except TimeoutError as exc:
        finish_codex_run(run_id, "timeout", error=str(exc))
        raise
    except Exception as exc:
        finish_codex_run(run_id, "error", error=str(exc))
        raise

    result = complete_progress_check(run_id, raw_input, output_text)
    BRIDGE_RESPONSE_PATH.unlink(missing_ok=True)
    return result


def check_progress_update(task_id: str, progress_text: str) -> dict[str, Any]:
    if not has_clickup_config():
        raise ValueError("尚未設定 ClickUp 連線。")
    with get_db() as conn:
        project = get_clickup_project(conn, task_id)
        session_id = get_session(conn)["id"]
        if project is None:
            set_session_error(conn, session_id, "找不到選擇的 ClickUp 專案，請重新同步或重新選擇。")
            raise ValueError("找不到選擇的 ClickUp 專案，請重新同步或重新選擇。")
        project_name = project["name"]

    clean_text = build_progress_input(project_name, progress_text)
    if not clean_text:
        raise ValueError("請輸入進度內容。")

    now = utc_now()
    try:
        formatted, evaluation, question_result, final_text, run_id = refine_progress(
            clean_text,
            session_id,
        )
    except Exception as exc:
        with get_db() as conn:
            set_session_error(conn, session_id, f"Codex workflow failed: {exc}")
        raise

    with get_db() as conn:
        entry_id = save_refinement(
            conn,
            session_id,
            clean_text,
            formatted,
            evaluation,
            question_result,
            final_text,
            now,
        )
        keep_only_latest_progress(conn, session_id, entry_id, run_id)

    return {
        "ok": True,
        "entry_id": entry_id,
        "raw_input": clean_text,
        "formatted": formatted,
        "evaluation": evaluation,
        "question_result": question_result,
        "final_text": final_text,
    }


def build_codex_direct_evaluation() -> dict[str, Any]:
    return {
        "score": 100,
        "summary_sentences": [
            "整體內容已由 VSCode Codex 依進度格式直接整理完成。",
            "主要優點是格式明確，已可作為進度更新使用。",
            "若需要更完整的評分，仍可補充數字、風險與後續安排。",
        ],
        "subscores": [],
        "missing_fields": [],
        "strengths": ["由 VSCode Codex 依進度格式規則直接更新。"],
        "ready_for_review": True,
    }


def build_empty_question_result() -> dict[str, list[dict[str, str]]]:
    return {"questions": []}
