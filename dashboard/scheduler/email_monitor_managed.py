"""CASINOINBOT adapter that suppresses email runs with no alert-worthy mail."""

from __future__ import annotations

import os
import sys
from pathlib import Path


SOURCE_DIR = Path("/home/kaekun/email_monitor")
os.chdir(SOURCE_DIR)
sys.path.insert(0, str(SOURCE_DIR))

import run_forever  # noqa: E402


_original_send = run_forever.main._send_urgent_and_briefing


def _send_only_actionable(cfg, logger, conn, tg_sender, buckets, state):
    if not buckets.urgent and not buckets.briefing:
        logger.info("알림 대상 중요·긴급 메일 없음 - 정상/무변화 텔레그램 알림 생략")
        return
    return _original_send(cfg, logger, conn, tg_sender, buckets, state)


run_forever.main._send_urgent_and_briefing = _send_only_actionable

if __name__ == "__main__":
    run_forever.run_forever()
