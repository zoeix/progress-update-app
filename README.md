# progress-update-app

本機進度更新工具。使用者可以選擇 ClickUp 專案、輸入進度內容，透過 Codex 檢查進度品質與產生待補充問題，最後手動上傳目前內容到 ClickUp。

## 功能

- 每次啟動服務後先進入 ClickUp 登入頁。
- 同步 ClickUp list 內的專案清單。
- 使用單一「進度內容」編輯框撰寫週報草稿。
- 顯示電腦本機當日更新日期。
- 以 PM 內容顆粒度評分檢查進度是否夠具體。
- 顯示待補充問題。
- 手動上傳進度到 ClickUp。
- 支援重設目前資料。
- 支援結束服務並清空目前資料。

## 環境需求

- Python 3.11+
- Codex CLI
- ClickUp token
- ClickUp list id

Python 套件列在 `requirements.txt`。

## 安裝

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

## 啟動

macOS / Linux：

```bash
.venv/bin/python app.py
```

Windows PowerShell：

```powershell
.venv\Scripts\python.exe app.py
```

啟動後開啟：

```text
http://127.0.0.1:8000
```

## 使用流程

1. 啟動本機服務。
2. 在登入頁輸入 `CLICKUP_TOKEN` 與 `CLICKUP_LIST_ID`。
   - Windows 若 `codex` 不在 PATH，可在 `CODEX_BIN` 填入 `codex.cmd` 完整路徑。
3. 進入進度頁後選擇專案。
4. 確認右側更新日期。
5. 在「進度內容」輸入草稿。
6. 點擊「檢查進度」。
7. 依評分與待補充問題修改內容。
8. 確認內容後點擊「上傳進度」。

## ClickUp 連線腳本

```bash
.venv/bin/python scripts/connect_clickup.py
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

建議進度格式：

```text
# 本週進度：
1. [進度] 已完成...

# 下週進度：
1. [待確認] 預計...
```

## 右上角操作

- `重設`：清空目前草稿、問題、評分與 Codex run，服務繼續執行。
- `結束`：清空目前資料並關閉本機服務。

## 評分

品質分數用來幫助 PM 自我檢查進度是否完整、聚焦、可量化、容易被非技術讀者理解，並呈現後續影響。

評分項目：

- 完整度：10 分
- 顆粒度：20 分
- 量化與風險：30 分
- 解釋性：20 分
- 影響力與延展：20 分

## 合法 Tag

- `[Risk: Low]`
- `[Risk: Medium]`
- `[Risk: High]`
- `[里程碑]`
- `[進度]`
- `[待確認]`

## 資料儲存

- SQLite database：`data/app.db`
- Prompt 檔案：`prompts/`
- ClickUp 設定：本機 `.env`
- Codex 路徑設定：本機 `.env` 的 `CODEX_BIN`

ClickUp token 不會送入 Codex prompt。

## 文件

- [MVP_SPEC.md](MVP_SPEC.md)：MVP 規格。
- [TASKS.md](TASKS.md)：任務清單與目前狀態。
