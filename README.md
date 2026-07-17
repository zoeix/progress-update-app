# progress-update-app

本機進度更新工具。使用者可以選擇 ClickUp 專案、輸入進度內容，透過 Codex 檢查進度品質與產生待補充問題，最後手動上傳目前內容到 ClickUp。

## 功能

- 每次啟動服務後先進入 ClickUp 登入頁。
- 同步 ClickUp list 內的專案清單。
- 使用單一「進度內容」編輯框撰寫週報草稿。
- 顯示本機當日更新日期，時區使用 `Asia/Taipei`。
- 以 Manager Readiness Score 檢查進度是否足以支援主管判斷。
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

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 啟動

```bash
.venv/bin/python app.py
```

啟動後開啟：

```text
http://127.0.0.1:8000
```

## 使用流程

1. 啟動本機服務。
2. 在登入頁輸入 `CLICKUP_TOKEN` 與 `CLICKUP_LIST_ID`。
3. 進入進度頁後選擇專案。
4. 確認右側更新日期。
5. 在「進度內容」輸入草稿。
6. 點擊「檢查進度」。
7. 依評分與待補充問題修改內容。
8. 確認內容後點擊「上傳進度」。

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

品質分數使用 Manager Readiness Score，重點是主管是否能直接判斷專案狀態與是否需要介入。

評分項目：

- 背景：15 分
- 目前狀態：30 分
- 下週計畫：20 分
- 健康度：20 分
- 風險 / Tag：15 分

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

ClickUp token 不會送入 Codex prompt。

## 文件

- [MVP_SPEC.md](MVP_SPEC.md)：MVP 規格。
- [TASKS.md](TASKS.md)：任務清單與目前狀態。
