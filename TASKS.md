# progress-update-app Tasks

## Phase 1: Progress Content Refinement Only

ClickUp API key, task selection, and ClickUp writes are intentionally deferred.

## Milestone 1: Local App Skeleton

- [x] Create Python project files.
  - [x] Add `requirements.txt`.
  - [x] Add `.gitignore`.
  - [x] Add `app.py`.
  - [x] Add `templates/index.html`.
- [x] Add FastAPI app startup.
  - [x] Serve homepage at `GET /`.
  - [ ] Run locally with `uvicorn app:app --reload`.
- [x] Add SQLite initialization.
  - [x] Create `data/app.db` at runtime.
  - [x] Create Phase 1 tables: `sessions`, `progress_entries`, `questions`.
  - [x] Create or load one default session.
- [x] Show current session state on the homepage.

Acceptance:

- [ ] App starts locally.
- [ ] Browser can open `http://127.0.0.1:8000`.
- [ ] SQLite database is created automatically.
- [ ] Homepage displays the default session and state.

## Milestone 2: ClickUp API Key Flow

Deferred to Phase 2.

- [ ] Add API key entry UI.
- [ ] Add backend route to receive the API key.
- [ ] Validate the API key with ClickUp.
- [ ] Store only safe metadata in SQLite.
- [ ] Store the actual API key outside `.venv`.
- [ ] Keep the API key out of Codex prompts, prompt snapshots, logs, and UI debug output.

Acceptance:

- [ ] Missing API key puts the app in `needs_api_key`.
- [ ] Valid API key moves the app to `editing_progress`.
- [ ] Invalid API key shows a clear error.

## Milestone 3: Progress Input Flow

- [x] Add progress input form.
- [x] Save raw progress input to SQLite.
- [x] Create `progress_entries` records.
- [x] Add temporary local refinement output for UI and DB validation.
- [x] Show formatted update, score, and questions on the page.
- [x] Add answer flow for follow-up questions.
- [x] Re-run refinement with answered questions.
- [x] Add editable weekly draft.
- [x] Save edited draft content.
- [x] Re-run structured evaluation with edited draft content.
- [x] Simplify UI to weekly draft, follow-up questions, and quality score.
- [x] Add target field metadata for follow-up questions.
- [x] Use prompt files for local formatting, scoring, and question rules.
- [x] Add local tag output for weekly draft items.

Acceptance:

- [x] User can submit progress text.
- [x] Raw input is saved.
- [x] Formatted output appears in the UI.
- [x] Session moves to `needs_more_info` or `ready_for_review`.

## Milestone 4: Codex Workflow

Deferred until the Phase 1 local flow is stable.

- [x] Add Codex subprocess wrapper.
- [x] Add formatter prompt.
- [x] Add granularity guidance prompt.
- [x] Add completeness evaluator prompt.
- [x] Add question generator prompt.
- [x] Add prompt file loader.
- [x] Store each prompt snapshot and output in `codex_runs`.
- [x] Parse and validate JSON outputs.
- [x] Handle Codex errors and timeouts.
- [x] Remove local Python fallback as a content judgment source.
- [x] Show Codex workflow errors in the UI.

Acceptance:

- [ ] User input produces real Codex formatted output.
- [ ] Completeness score is saved and displayed.
- [ ] Follow-up questions are saved and displayed.
- [ ] ClickUp API key is never sent to Codex.

## Milestone 5: Review and ClickUp Update

- [ ] Add final preview page or section.
- [ ] Build deterministic ClickUp update payload.
- [ ] Require explicit user confirmation.
- [ ] Call ClickUp API after confirmation.
- [ ] Save payload snapshot, response snapshot, and update status.
- [ ] Support retry after failure.

Acceptance:

- [ ] User can review exact final content before update.
- [ ] Backend updates ClickUp only after confirmation.
- [ ] Success state is saved as `updated`.
- [ ] Failure state is saved as `update_failed`.

## Later

- [ ] Add session list and session switching.
- [ ] Add better local secret storage with OS keyring.
- [ ] Add HTMX partial updates.
- [ ] Add Codex SDK support if subprocess becomes limiting.
- [ ] Add exported history or reports.
