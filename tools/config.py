from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
ENV_PATH = BASE_DIR / ".env"
PROMPTS_DIR = BASE_DIR / "prompts"
load_dotenv(ENV_PATH)

PROMPT_FILES = {
    "formatted": "formatted.md",
    "evaluation": "evaluation.md",
    "question_result": "question_result.md",
}
VALID_TAGS = {"[Risk: Low]", "[Risk: Medium]", "[Risk: High]", "[里程碑]", "[進度]", "[待確認]"}
CODEX_TIMEOUT_SECONDS = int(os.environ.get("CODEX_TIMEOUT_SECONDS", "90"))
CODEX_MODEL = os.environ.get("CODEX_MODEL", "").strip()
CLICKUP_API_BASE = "https://api.clickup.com/api/v2"
CLICKUP_PAGE_SIZE = 100

STATE_EDITING = "editing_progress"
STATE_NEEDS_MORE_INFO = "needs_more_info"
STATE_READY_FOR_REVIEW = "ready_for_review"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

