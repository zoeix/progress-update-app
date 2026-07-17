# progress-update-app MVP 規格

## 目標

建立一個本機網頁工具，讓使用者可以輸入專案進度，透過 Codex 依固定格式整理內容、評估主管是否能直接判斷專案狀態，並在使用者確認後上傳到 ClickUp。

此工具的核心不是美化文字，而是讓進度更新足以支援主管做管理決策。

## 使用者流程

1. 使用者以 `.venv/bin/python app.py` 啟動本機服務。
2. 每次服務啟動後，首頁會先導向登入頁。
3. 使用者輸入 ClickUp token 與 list id。
4. 使用者可選填 Codex 執行檔路徑；若系統找得到 Codex，登入頁會自動帶入。
5. 後端驗證 ClickUp 連線，並同步該 list 的專案清單。
6. 使用者進入進度更新頁。
7. 使用者從專案選單選擇專案。
8. 右側顯示當日更新日期，日期取自電腦本機日期。
9. 使用者在單一「進度內容」編輯框輸入完整草稿。
10. 使用者點擊「檢查進度」。
11. 後端將專案名稱與進度內容送入 Codex workflow。
12. Codex 回傳格式化進度、Manager Readiness Score、缺漏資訊與追問。
13. UI 顯示評分與待補充問題。
14. 使用者可修改同一個進度內容編輯框後再次檢查。
15. 使用者可點擊「上傳進度」將目前編輯框內容上傳到 ClickUp。
16. 使用者可點擊「重設」清空目前草稿、問題、評分與 Codex run。
17. 使用者可點擊「結束」清空目前資料並關閉本機服務。

## 產品範圍

### 包含

- 本機 FastAPI 網頁服務。
- Jinja2 template 前端。
- SQLite 儲存 session、進度紀錄、問題與 Codex run。
- ClickUp token 與 list id 設定頁。
- ClickUp 專案清單同步。
- 單一進度內容編輯框。
- Codex workflow：
  - 格式化進度內容。
  - 依 Manager Readiness Score 評分。
  - 產生主管決策所需的追問。
- 前端顯示：
  - 專案選單。
  - 當日更新日期。
  - 進度內容編輯框。
  - 內容評分。
  - 待補充問題。
  - 重設、結束、檢查進度、上傳進度。
- 使用者明確點擊後才上傳到 ClickUp。

### 不包含

- 多使用者登入。
- 雲端部署。
- 桌面應用程式封裝。
- 多個 ClickUp workspace 管理。
- Codex streaming。
- 讓 Codex 直接呼叫 ClickUp API。
- 自動上傳 ClickUp。
- 複雜報表或分析儀表板。

## 畫面行為

### 登入頁

- 顯示 ClickUp 設定表單。
- 欄位：
  - `CLICKUP_TOKEN`
  - `CLICKUP_LIST_ID`
  - `CODEX_BIN`，選填
- 若系統能找到 Codex 執行檔，`CODEX_BIN` 會自動帶入。
- Windows 使用者可填入 `codex.cmd` 完整路徑。
- 登入成功後同步 ClickUp 專案清單並進入首頁。
- 每次服務重啟後都要重新登入，避免直接跳入進度頁。

### 進度頁

- 左上顯示產品標題。
- 右上顯示：
  - `重設`
  - `結束`
- 表單上方同一列顯示：
  - 專案名稱選單。
  - 更新日期。
- 進度內容使用單一編輯框，建議格式：

```text
# 本週進度：
1. [進度] 已完成...

# 下週進度：
1. [待確認] 預計...
```

- 「檢查進度」會執行 Codex workflow。
- 「上傳進度」會將目前編輯框內容上傳到 ClickUp。
- 「重設」只清空目前資料，服務繼續執行。
- 「結束」清空目前資料並關閉服務。

## 進度格式

Codex 格式化後的 JSON 結構：

```json
{
  "project_name": "",
  "this_week_progress": [
    {
      "tag": "[進度]",
      "text": ""
    }
  ],
  "next_week_plan": [
    {
      "tag": "[待確認]",
      "text": ""
    }
  ],
  "notes": []
}
```

最終文字格式不包含更新日期：

```text
專案名稱: 專案名稱

# 本週進度：
1. [進度] ...

# 下週進度：
1. [待確認] ...
```

## 合法 Tag

- `[Risk: Low]`
- `[Risk: Medium]`
- `[Risk: High]`
- `[里程碑]`
- `[進度]`
- `[待確認]`

## Manager Readiness Score

評分目的：判斷這份進度是否足以讓主管在不額外追問的情況下掌握狀態、判斷是否需要介入，並安排後續工作。

子項目：

- 背景：15 分
- 目前狀態：30 分
- 下週計畫：20 分
- 健康度：20 分
- 風險 / Tag：15 分

高分代表主管能回答：

- 現在做到哪裡？
- 下一步是什麼？
- 專案健康度如何？
- 是否需要主管介入？

## 架構

```text
Browser UI
  -> FastAPI backend
      -> SQLite local database
      -> Codex workflow
      -> ClickUp API client
```

## 後端責任

- 管理本機 session 狀態。
- 初始化 SQLite。
- 驗證 ClickUp token 與 list id。
- 同步 ClickUp 專案清單。
- 建立 Codex workflow prompt。
- 解析與驗證 Codex JSON output。
- 儲存 prompt snapshot、output、錯誤與評分。
- 在 Codex 失敗時將錯誤顯示在 UI。
- 上傳進度到 ClickUp。
- 重設或結束服務。

## Codex 責任

Codex 只負責進度內容處理，不得接觸 ClickUp token，也不得呼叫 ClickUp API。

Codex workflow 一次完成：

- 格式化進度。
- 評估 Manager Readiness Score。
- 判斷既有問題狀態。
- 產生最多 3 個追問。

輸出必須是合法 JSON。

## SQLite 資料表

### `sessions`

- `id`
- `title`
- `state`
- `running_summary`
- `last_error`
- `last_notice`
- `created_at`
- `updated_at`

### `progress_entries`

- `id`
- `session_id`
- `raw_input`
- `formatted_json`
- `evaluation_json`
- `questions_json`
- `final_text`
- `created_at`

### `questions`

- `id`
- `session_id`
- `entry_id`
- `question`
- `reason`
- `priority`
- `target_field`
- `status`
- `review_reason`
- `previous_question_id`
- `answer`
- `answered_at`
- `created_at`

### `codex_runs`

- `id`
- `session_id`
- `entry_id`
- `role`
- `prompt_snapshot`
- `output_text`
- `output_json`
- `status`
- `error`
- `created_at`
- `updated_at`

### `clickup_projects`

- `id`
- `name`
- `status`
- `url`
- `raw_json`
- `synced_at`

## 成功標準

- 使用者可以啟動本機服務。
- 每次重啟後會先進入登入頁。
- 使用者可以完成 ClickUp 設定並同步專案清單。
- 使用者可以在單一編輯框輸入進度內容。
- 使用者可以檢查進度並看到評分與追問。
- 使用者可以修改內容後再次檢查。
- 使用者可以明確上傳目前內容到 ClickUp。
- 使用者可以重設目前資料。
- 使用者可以結束服務。
