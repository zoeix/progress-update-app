from __future__ import annotations

import json
import os
import threading
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from tools.clickup import (
    connect_clickup,
    find_codex_bin,
    get_clickup_list_id,
    get_clickup_project,
    get_clickup_project_count,
    get_clickup_projects,
    get_clickup_token,
    has_clickup_config,
    post_clickup_comment,
    set_clickup_session_active,
)
from tools.config import BASE_DIR, utc_now
from tools.db import (
    get_db,
    get_latest_entry,
    get_questions,
    get_session,
    init_db,
    parse_json_field,
    reset_progress_data,
    save_refinement,
    serialize_latest_progress,
    set_session_error,
    set_session_notice,
)
from tools.formatting import (
    build_clickup_upload_content,
    build_draft_form_state,
    build_progress_input,
    render_final_text,
    today_label,
)
from tools.progress import (
    build_codex_direct_evaluation,
    build_empty_question_result,
    check_progress_update,
    check_progress_update_with_bridge,
    complete_progress_check,
    prepare_progress_check,
    refine_progress,
    validate_formatted_json,
)


app = FastAPI(title="Progress Update App")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def is_vscode_mode() -> bool:
    return os.environ.get("PROGRESS_UPDATE_VSCODE_MODE", "").strip() == "1"


@app.on_event("startup")
def on_startup() -> None:
    init_db()


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
    clean_token = clickup_token.strip()
    clean_list_id = clickup_list_id.strip()
    clean_codex_bin = codex_bin.strip()
    try:
        connect_clickup(clean_token, clean_list_id, clean_codex_bin)
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

    set_clickup_session_active(True)
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
                "vscode_mode": is_vscode_mode(),
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
    with get_db() as conn:
        reset_progress_data(conn)
    set_clickup_session_active(False)
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


@app.post("/codex/clickup/connect")
async def codex_clickup_connect(request: Request):
    payload: dict[str, Any] = {}
    body = await request.body()
    if body:
        try:
            raw_payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")
        payload = raw_payload

    token = str(payload.get("clickup_token") or get_clickup_token()).strip()
    list_id = str(payload.get("clickup_list_id") or get_clickup_list_id()).strip()
    codex_bin = str(payload.get("codex_bin") or os.environ.get("CODEX_BIN", "")).strip()
    try:
        project_count = connect_clickup(token, list_id, codex_bin)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"ClickUp 連線失敗：{exc}") from exc

    set_clickup_session_active(True)
    return {
        "ok": True,
        "message": "ClickUp 連線成功，已同步專案清單。",
        "project_count": project_count,
        "clickup_list_id": list_id,
    }


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
    try:
        if is_vscode_mode():
            check_progress_update_with_bridge(task_id, progress_text)
        else:
            check_progress_update(task_id, progress_text)
    except Exception:
        return RedirectResponse("/", status_code=303)

    return RedirectResponse("/", status_code=303)


@app.post("/api/progress/check")
async def api_progress_check(request: Request):
    if not has_clickup_config():
        raise HTTPException(status_code=401, detail="尚未設定 ClickUp 連線。")
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    task_id = str(payload.get("task_id", "")).strip()
    progress_text = str(payload.get("progress_text", "")).strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    if not progress_text:
        raise HTTPException(status_code=400, detail="progress_text is required")

    try:
        return check_progress_update(task_id, progress_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Codex workflow failed: {exc}") from exc


@app.post("/api/progress/check/prepare")
async def api_progress_check_prepare(request: Request):
    if not has_clickup_config():
        raise HTTPException(status_code=401, detail="尚未設定 ClickUp 連線。")
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    task_id = str(payload.get("task_id", "")).strip()
    progress_text = str(payload.get("progress_text", "")).strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    if not progress_text:
        raise HTTPException(status_code=400, detail="progress_text is required")

    try:
        return prepare_progress_check(task_id, progress_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/progress/check/complete")
async def api_progress_check_complete(request: Request):
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    raw_run_id = payload.get("run_id")
    try:
        run_id = int(raw_run_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="run_id is required") from exc
    raw_input = str(payload.get("raw_input", "")).strip()
    if not raw_input:
        raise HTTPException(status_code=400, detail="raw_input is required")
    if "output" in payload:
        output = payload["output"]
    elif "output_text" in payload:
        output = str(payload["output_text"])
    else:
        raise HTTPException(status_code=400, detail="output or output_text is required")

    try:
        return complete_progress_check(run_id, raw_input, output)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Codex workflow failed: {exc}") from exc


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

    try:
        formatted, evaluation, question_result, final_text = refine_progress(
            clean_text,
            session_id,
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
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Progress Update web app.")
    parser.add_argument(
        "--vscode",
        action="store_true",
        help="Use bridge/prompt.md and bridge/res.json instead of calling the Codex CLI.",
    )
    args = parser.parse_args()
    if args.vscode:
        os.environ["PROGRESS_UPDATE_VSCODE_MODE"] = "1"

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
