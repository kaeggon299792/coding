"""Minute-level work-note Telegram reminder worker managed by CASINOINBOT."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import dashboard_db  # noqa: E402
from services import work_notes  # noqa: E402
from utils import setup_logger  # noqa: E402


logger = setup_logger("work_note_reminders")


def run_once():
    connection = dashboard_db()
    try:
        return work_notes.send_due_reminders(connection)
    finally:
        connection.close()


def main():
    interval = max(60, int(os.environ.get("WORK_NOTE_REMINDER_INTERVAL_SECONDS", "60")))
    logger.info("업무노트 알림 확인을 시작합니다 (간격 %d초).", interval)
    while True:
        try:
            result = run_once()
            if result["sent"] or result["failed"]:
                logger.info("업무노트 알림 처리: sent=%d failed=%d", result["sent"], result["failed"])
        except Exception as error:
            logger.error("업무노트 알림 처리 실패: %s", error)
        time.sleep(interval)


if __name__ == "__main__":
    main()
