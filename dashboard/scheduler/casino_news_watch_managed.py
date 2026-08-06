"""CASINOINBOT adapter for configurable casino-news polling intervals."""

from __future__ import annotations

import os
import sys
from pathlib import Path


SOURCE_DIR = Path("/home/kaekun/casino_news_watch")
os.chdir(SOURCE_DIR)
sys.path.insert(0, str(SOURCE_DIR))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(1, str(PROJECT_ROOT))

import always_on_runner  # noqa: E402
import openai_analyzer  # noqa: E402
import telegram_sender  # noqa: E402
from services.news_alert_policy import apply_news_alert_policy  # noqa: E402


apply_news_alert_policy(openai_analyzer, telegram_sender)

always_on_runner.INTERVAL_SECONDS = max(
    60, int(os.environ.get("CASINO_NEWS_INTERVAL_SECONDS", "900"))
)

if __name__ == "__main__":
    always_on_runner.run_forever()
