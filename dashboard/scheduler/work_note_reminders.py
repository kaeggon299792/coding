"""Minute-level member notification worker managed by CASINOINBOT."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import dashboard_db  # noqa: E402
from services import comment_telegram_notifications, work_notes  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("work_note_reminders")


def run_once():
    connection = dashboard_db()
    try:
        reminders = work_notes.send_due_reminders(connection)
        comments = comment_telegram_notifications.process_pending(connection, limit=20)
        return {"reminders": reminders, "comments": comments}
    finally:
        connection.close()


def main():
    interval = max(60, int(os.environ.get("WORK_NOTE_REMINDER_INTERVAL_SECONDS", "60")))
    logger.info("회원 알림 확인을 시작합니다(간격 %d초).", interval)
    while True:
        try:
            result = run_once()
            reminders = result["reminders"]
            comments = result["comments"]
            if reminders["sent"] or reminders["failed"]:
                logger.info("업무노트 알림: sent=%d failed=%d",
                            reminders["sent"], reminders["failed"])
            if comments["claimed"]:
                logger.info("댓글 알림 큐: claimed=%d sent=%d failed=%d",
                            comments["claimed"], comments["sent"], comments["failed"])
        except Exception as error:
            logger.error("회원 알림 처리 실패: %s", type(error).__name__)
        time.sleep(interval)


if __name__ == "__main__":
    main()
