from __future__ import annotations

import os
import threading

from fastapi import FastAPI, Form, Request
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
from tools.config import BASE_DIR
from tools.db import (
    get_db,
    get_latest_entry,
    get_questions,
    get_session,
    init_db,
    parse_json_field,
    reset_progress_data,
    set_session_error,
    set_session_notice,
)
from tools.formatting import (
    build_clickup_upload_content,
    build_draft_form_state,
    today_label,
)
from tools.progress import (
    check_progress_update,
    check_progress_update_with_bridge,
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
