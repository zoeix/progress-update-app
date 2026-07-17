# progress-update-app 任務清單

## 目前 MVP 狀態

此專案已從早期「純進度整理」版本，更新為可連接 ClickUp、同步專案清單、檢查進度品質並上傳進度的本機工具。

目前主要流程：

1. 啟動本機服務。
2. 每次重啟後先進入 ClickUp 登入頁。
3. 同步 ClickUp 專案清單。
4. 選擇專案。
5. 在單一進度內容編輯框輸入草稿。
6. 點擊「檢查進度」執行 Codex workflow。
7. 查看 Manager Readiness Score 與待補充問題。
8. 視需要修改內容並再次檢查。
9. 點擊「上傳進度」寫入 ClickUp。
10. 可使用「重設」清空目前資料，或使用「結束」清空資料並關閉服務。

## 已完成

### 本機服務

- [x] 建立 FastAPI app。
- [x] 建立 Jinja2 template 前端。
- [x] 使用 `.venv/bin/python app.py` 啟動服務。
- [x] 服務監聽 `http://127.0.0.1:8000`。
- [x] 初始化 SQLite database。
- [x] 建立預設 session。

### ClickUp 設定與專案清單

- [x] 建立 ClickUp 設定頁。
- [x] 支援輸入 `CLICKUP_TOKEN`。
- [x] 支援輸入 `CLICKUP_LIST_ID`。
- [x] 支援選填 `CODEX_BIN`。
- [x] 登入頁會自動偵測 Codex 路徑，找不到時留空讓使用者自行填入。
- [x] 登入成功後將 `CODEX_BIN` 寫入 `.env` 與目前程序環境變數。
- [x] 驗證 ClickUp 連線。
- [x] 同步 ClickUp list 內的 task 作為專案清單。
- [x] 將專案清單存入 SQLite。
- [x] 每次服務重啟後先回到登入頁。

### 進度輸入 UI

- [x] 專案名稱使用下拉選單。
- [x] 更新日期顯示在專案選單旁。
- [x] 更新日期取自電腦本機當日日期。
- [x] 本週進度與下週進度合併為單一「進度內容」編輯框。
- [x] 編輯框直接對應 prompt 產出的最終格式。
- [x] 編輯框高度縮小，讓首頁第一眼可看到更多內容。
- [x] 「整理進度」文案改為「檢查進度」。
- [x] 右上角移除 session state 顯示。
- [x] 右上角顯示「重設」與「結束」。

### Prompt 與 Codex Workflow

- [x] 建立 `prompts/format_progress.md`。
- [x] 建立 `prompts/quality_score.md`。
- [x] 建立 `prompts/question_generation.md`。
- [x] 建立 `prompts/granularity_guidance.md`。
- [x] 將品質評分改為 Manager Readiness Score。
- [x] 評分項目改為：背景、目前狀態、下週計畫、健康度、風險 / Tag。
- [x] 從 format prompt 移除日期欄位與日期輸出。
- [x] Codex workflow 一次完成格式化、評分、問題狀態檢查與追問產生。
- [x] Codex output 必須解析為 JSON。
- [x] Codex JSON 解析失敗時顯示 output preview，方便除錯。
- [x] Codex subprocess 改在 `/tmp` 執行，避免專案 `AGENTS.md` 污染輸出。

### 評分與追問

- [x] 顯示總分。
- [x] 顯示 5 個簡短子項目。
- [x] 顯示待補充問題。
- [x] 問題依主管決策需求產生。
- [x] 支援上一輪問題狀態檢查。

### 上傳與資料管理

- [x] 「上傳進度」會將目前進度內容上傳到 ClickUp。
- [x] 「重設」會清空目前草稿、問題、評分與 Codex run。
- [x] 「結束」會清空目前資料並關閉服務。
- [x] ClickUp token 不送入 Codex prompt。

## 待辦

### 穩定性

- [ ] 增加 Codex workflow 的自動化測試。
- [ ] 增加 ClickUp API 失敗情境測試。
- [ ] 增加 SQLite migration 測試。
- [ ] 增加表單欄位缺漏時的錯誤顯示測試。
- [ ] 檢查服務結束流程在不同作業系統上的表現。

### 使用體驗

- [ ] 顯示目前上傳成功後的 ClickUp task 連結。
- [ ] 上傳前加入更明確的內容預覽。
- [ ] 在待補充問題點擊後，自動聚焦進度內容編輯框。
- [ ] 增加「複製進度內容」按鈕。
- [ ] 增加「重新同步專案清單」按鈕。

### 資料與安全

- [ ] 改善 ClickUp token 儲存方式，評估 OS keyring。
- [ ] 避免 `.env` 內容出現在任何 debug output。
- [ ] 增加 Codex prompt snapshot 的敏感資訊檢查。
- [ ] 增加資料庫清理策略。

### 文件

- [x] 將 `MVP_SPEC.md` 改為繁體中文。
- [x] 將 `TASKS.md` 改為繁體中文。
- [x] 更新文件以符合目前單一進度內容編輯框。
- [x] 更新文件以符合 Manager Readiness Score。
- [x] 更新文件以符合重設與結束流程。
- [ ] 補充本機啟動與重啟操作說明。
- [ ] 補充常見錯誤排查。

## 驗收標準

- [x] 使用者可以啟動本機服務。
- [x] 使用者每次重啟後會先看到登入頁。
- [x] 使用者可以登入 ClickUp 並同步專案清單。
- [x] 使用者可以選擇專案。
- [x] 使用者可以看到當日更新日期。
- [x] 使用者可以在單一進度內容框編輯草稿。
- [x] 使用者可以檢查進度。
- [x] 使用者可以看到 Manager Readiness Score。
- [x] 使用者可以看到待補充問題。
- [x] 使用者可以上傳進度到 ClickUp。
- [x] 使用者可以重設目前資料。
- [x] 使用者可以結束服務。
