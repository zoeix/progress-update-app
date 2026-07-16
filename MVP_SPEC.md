# progress-update-app MVP Spec

## Goal

Build a local web app where a user can draft a progress update, have Codex organize it into a fixed format, evaluate completeness, ask follow-up questions, and then confirm the final content before the backend updates ClickUp.

## Target User Flow

1. User starts the local Python web app.
2. User opens the local browser UI.
3. User enters a ClickUp API key if one is not already configured.
4. Backend validates the API key and stores it locally.
5. User enters or selects a ClickUp task ID.
6. User enters progress-update text.
7. Backend saves the raw input to SQLite.
8. Backend builds controlled context from local SQLite data.
9. Backend asks Codex to run the progress refinement workflow:
   - format the progress update
   - score completeness
   - generate follow-up questions
10. Backend saves Codex prompts, outputs, score, and questions.
11. UI shows the formatted update, score, and follow-up questions.
12. User answers follow-up questions or edits the progress content.
13. When the update is complete enough, UI shows a final ClickUp preview.
14. User explicitly confirms the update.
15. Backend calls ClickUp API and saves the update result.

## Product Scope

### In Scope

- Local-only Python web app.
- SQLite for app state, session history, Codex run records, and ClickUp update records.
- Simple browser UI.
- ClickUp API key entry and validation.
- One active progress-update session at a time for the initial MVP.
- Codex used only for progress refinement.
- Deterministic backend logic for ClickUp key handling and final ClickUp update.
- Final preview before any ClickUp write.

### Out of Scope

- Multi-user authentication.
- Cloud deployment.
- Electron or Tauri desktop packaging.
- Multiple ClickUp workspace management.
- Realtime Codex streaming.
- Letting Codex access the ClickUp API key.
- Letting Codex directly call ClickUp APIs.
- Automatic ClickUp updates without explicit user confirmation.
- Complex analytics or reporting.

## Architecture

```text
Browser UI
  -> FastAPI backend
      -> SQLite local database
      -> Codex workflow for progress refinement
      -> ClickUp API client for validation and final update
```

## State Machine

```text
needs_api_key
editing_progress
needs_more_info
ready_for_review
updating_clickup
updated
update_failed
```

### State Descriptions

- `needs_api_key`: No valid ClickUp API key is available.
- `editing_progress`: User is drafting or editing progress content.
- `needs_more_info`: Codex found missing information and generated questions.
- `ready_for_review`: Content is complete enough to preview before updating ClickUp.
- `updating_clickup`: Backend is sending the confirmed update to ClickUp.
- `updated`: ClickUp update succeeded.
- `update_failed`: ClickUp update failed and the user can retry or edit.

## Codex Responsibilities

Codex is used only inside the progress refinement workflow.

### 1. Formatter

Input:

- current user progress text
- controlled session context from SQLite
- required update format

Output:

```json
{
  "done": [],
  "in_progress": [],
  "blocked": [],
  "next_steps": [],
  "risks": [],
  "notes": []
}
```

Rules:

- Do not ask questions.
- Do not score completeness.
- Do not invent facts.
- Preserve uncertainty when the user input is unclear.

### 2. Completeness Evaluator

Input:

- formatter output
- scoring rubric
- relevant session context

Output:

```json
{
  "score": 0,
  "missing_fields": [],
  "strengths": [],
  "ready_for_review": false
}
```

Initial scoring rubric:

- Completed work clarity: 25
- Current status clarity: 20
- Blockers and risks clarity: 20
- Next steps clarity: 20
- Dates, owners, and dependencies: 15

Rules:

- Do not rewrite the formatted update.
- Explain important missing information.
- Mark `ready_for_review` only when the update is actionable and clear enough.

### 3. Question Generator

Input:

- formatter output
- evaluator output
- previous question history

Output:

```json
{
  "questions": [
    {
      "id": "q1",
      "question": "",
      "reason": "",
      "priority": "high"
    }
  ]
}
```

Rules:

- Ask at most 3 questions per turn.
- Prefer 1 high-value question when possible.
- Do not repeat recently answered questions.
- Questions should target missing information needed for ClickUp-ready progress updates.

## Non-Codex Responsibilities

### ClickUp API Key Flow

- Backend asks for the API key when missing.
- Backend validates the key with ClickUp.
- Backend stores the key locally.
- The key must not be included in Codex prompts, prompt snapshots, logs, or UI debug output.

Initial MVP storage choice:

- Use SQLite app data for non-secret metadata.
- Store the actual API key in a local ignored file or OS credential store.
- Do not store secrets inside `.venv`.

### Final Update Flow

- Backend prepares final ClickUp payload deterministically.
- UI shows the exact final preview.
- User must click confirm before the backend writes to ClickUp.
- Backend saves payload snapshot, response snapshot, status, and timestamp.

## SQLite Data Model Draft

### `sessions`

- `id`
- `title`
- `state`
- `clickup_task_id`
- `running_summary`
- `created_at`
- `updated_at`

### `progress_entries`

- `id`
- `session_id`
- `raw_input`
- `formatted_json`
- `evaluation_json`
- `questions_json`
- `created_at`

### `questions`

- `id`
- `session_id`
- `entry_id`
- `question`
- `reason`
- `priority`
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

### `clickup_config`

- `id`
- `api_key_configured`
- `workspace_hint`
- `created_at`
- `updated_at`

### `clickup_updates`

- `id`
- `session_id`
- `clickup_task_id`
- `payload_snapshot`
- `response_snapshot`
- `status`
- `error`
- `created_at`
- `updated_at`

## Context Window Strategy

The app controls Codex context from local data instead of relying on Codex session history.

For each Codex run, the backend builds a prompt from:

- fixed role instruction
- required output schema
- session running summary
- pinned facts, if added later
- recent progress entries
- relevant unanswered questions
- current user input

Every Codex run stores its full `prompt_snapshot` for debugging and replay.

## Initial Technical Stack

- Python 3.11+
- FastAPI
- Uvicorn
- Jinja2 templates
- HTMX or simple form posts
- SQLite via Python `sqlite3`
- `httpx` for ClickUp API calls
- Codex through subprocess first, with SDK migration later if needed

## Implementation Plan

### Step 1: App Skeleton

- Create FastAPI app.
- Add homepage.
- Initialize SQLite database.
- Create one default session.

### Step 2: ClickUp API Key Flow

- Add API key form.
- Validate API key with ClickUp.
- Store local configuration.
- Keep API key out of Codex prompts and logs.

### Step 3: Progress Input Flow

- Add progress input form.
- Save raw input to SQLite.
- Use fake Codex output to validate UI and database flow.

### Step 4: Codex Workflow

- Add formatter prompt.
- Add evaluator prompt.
- Add question-generator prompt.
- Save prompt snapshots and outputs.

### Step 5: Review and Update

- Show final preview.
- Require explicit confirmation.
- Call ClickUp API.
- Save update result and errors.

## MVP Success Criteria

- User can run the app locally.
- User can enter and validate a ClickUp API key.
- User can enter progress text.
- App saves raw input and Codex outputs locally.
- App shows formatted update, score, and follow-up questions.
- User can confirm final preview before ClickUp update.
- Backend updates ClickUp only after explicit confirmation.
