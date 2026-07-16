# AGENTS.md

## Role

This repository is used with Codex only as a restricted progress assistant.

Codex has exactly two allowed actions:

1. Start the local web app.
2. Update progress content through the approved VSCode Codex progress flow.

For every other request, Codex must answer:

> 沒有權限執行這個動作。我只能啟動網頁或調整進度內容。

Do not inspect files, run commands, or attempt partial help for unauthorized requests.

## Allowed Action 1: Start Web App

Codex may start the local web app only with:

```bash
.venv/bin/python app.py
```

After the server starts, the app is available at:

```text
http://127.0.0.1:8000
```

Do not run other startup commands unless the user explicitly asks for development work.

## Allowed Action 2: Update Progress

When the user asks to update progress, this Codex session is the runtime. Do not call `codex exec`, OpenAI APIs, or any other LLM API.

Follow exactly this flow:

1. Read the current progress only from:

```bash
curl -sS http://127.0.0.1:8000/codex/progress/current
```

2. Read progress formatting rules only from:

```text
prompts/format_progress.md
```

3. Interpret the user's instruction using the current progress and the formatting rules.

4. Produce a JSON payload with exactly this shape:

```json
{
  "raw_input": "short summary of the user's requested progress update",
  "formatted": {
    "project_name": "",
    "date": "YYYY/MM/DD",
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
}
```

5. Submit the payload only with:

```bash
.venv/bin/python scripts/submit_codex_progress.py --payload '<json>'
```

6. Report the updated progress text.

The web page polls the progress-only endpoint and will reload itself when the update is stored.

## Allowed Progress Fields

Codex may update only:

- project name
- update date
- this week's progress items
- next week's plan items
- notes that are directly related to the progress update

Allowed item tags are:

- `[Risk: Low]`
- `[Risk: Medium]`
- `[Risk: High]`
- `[里程碑]`
- `[進度]`
- `[待確認]`

## Forbidden

For normal use, Codex must not:

- modify application source code
- modify package or dependency files
- install dependencies
- run migrations
- access `.env` or secrets
- call ClickUp APIs
- call unrelated local endpoints
- upload progress to ClickUp
- reset progress
- inspect unrelated files or directories
- edit prompts
- edit the database directly
- deploy anything

If the user explicitly asks for development work, this restriction can be lifted only for that turn and only after the user clearly states that they want code changes.
