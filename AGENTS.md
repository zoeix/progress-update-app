# AGENTS.md

## Role
- 只能執行以下動作，其他禁止：
  1. 啟動app.py
  2. 檢查clickup連線
  3. 進行進度更新

For every other request, Codex must answer:

> 沒有權限執行這個動作。我只能啟動網頁或調整進度內容。

- Do not inspect files, run commands, or attempt partial help for unauthorized requests.

## Actions
1. 啟動app.py
- 檢查本地端是否有python虛擬環境，若沒有協助安裝：
macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

- Start the local web app only with:

```bash
.venv/bin/python app.py
```

After the server starts, the app is available at:

```text
http://127.0.0.1:8000
```

Do not run other startup commands unless the user explicitly asks for development work.

2. 檢查並設定 ClickUp 連線

- 先確認 app.py 已啟動。
- 必須呼叫正在執行中的本機 app endpoint，讓 web app 記憶體 session 進入已連線狀態：

macOS / Linux：

```bash
curl -sS -X POST http://127.0.0.1:8000/codex/clickup/connect
```

Windows PowerShell：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/codex/clickup/connect
```

成功會回傳：

```json
{
  "ok": true,
  "message": "ClickUp 連線成功，已同步專案清單。",
  "project_count": 0,
  "clickup_list_id": "..."
}
```

- 注意：`scripts/connect_clickup.py` 只會在該腳本自己的 Python 程序內執行連線與同步資料庫，不會設定正在執行中的 web app session。
- 因此進行進度更新前，不可只執行 `scripts/connect_clickup.py`；必須呼叫 `/codex/clickup/connect`。

3. 取得task_id清單

```bash
.venv/bin/python scripts/get_first_clickup_project.py
```

如果沒有資料，則打開網頁要求使用者填入參數，停止後續動作．

```
http://127.0.0.1:8000/login?
```

4. 進行進度更新
- 檢查app是否啟動
- 呼叫本機 app 的 ClickUp connect endpoint，確認正在執行中的 web app 已設定 ClickUp 連線：

macOS / Linux：

```bash
curl -sS -X POST http://127.0.0.1:8000/codex/clickup/connect
```

Windows PowerShell：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/codex/clickup/connect
```

- connect 成功後，取得task_id清單
- 依據使用者提供的進度內容，使用 script 執行完整流程：
  1. 將 `task_id` 與使用者輸入的進度送到 app 的 prepare endpoint。
  2. 取得 app 產生的 `prompt_snapshot`、`raw_input` 與 `run_id`。
  3. Codex 只能依照 `prompt_snapshot` 輸出指定 JSON 格式。
  4. 將 Codex output 與 `run_id`、`raw_input` 送回 app 的 complete endpoint。
  5. app 更新頁面內容。

- 只能用 script 執行進度檢查與更新，不可直接呼叫 API：

macOS / Linux：

```bash
.venv/bin/python scripts/check_progress_with_codex.py --task-id TASK_ID --progress-file progress.txt
```

Windows PowerShell：

```powershell
.venv\Scripts\python.exe scripts\check_progress_with_codex.py --task-id TASK_ID --progress-file progress.txt
```

- `progress.txt` 必須使用 UTF-8 編碼，避免 Windows 命令列直接傳中文造成亂碼。
- 如果不使用檔案，也可以用 stdin 傳入 UTF-8 進度文字：

macOS / Linux：

```bash
.venv/bin/python scripts/check_progress_with_codex.py --task-id TASK_ID --progress-stdin
```

Windows PowerShell：

```powershell
Get-Content progress.txt -Raw -Encoding UTF8 | .venv\Scripts\python.exe scripts\check_progress_with_codex.py --task-id TASK_ID --progress-stdin
```
