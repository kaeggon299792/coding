"""
email_monitor의 email_monitor.db를 읽기 전용으로 조회한다.

이 모듈은 email_monitor.db에 어떤 쓰기 작업도 하지 않는다. 광고/뉴스레터/단순
안내 메일(importance가 normal/low/irrelevant)은 기본 조회에서 제외한다.

email_monitor.db 스키마(email_monitor/database.py 기준):
  emails(id, account, folder, imap_uid, message_id, sender_name, sender_address,
         subject, received_at, processed_at, body_hash, mail_type, importance,
         importance_score, summary, deadline, reply_required, telegram_required,
         telegram_sent_at, marked_read_at, status, error_message, analysis_json)
"""

import json
import logging

from extensions import email_db_readonly
from utils import today_kst_str

logger = logging.getLogger("dashboard")

IMPORTANT_LEVELS = ("urgent", "high")
DONE_STATUSES = ("analyzed", "notified")


def _safe_query(query, params=()):
    connection = email_db_readonly()
    if connection is None:
        logger.warning("email_monitor.db에 연결할 수 없습니다(경로 미설정 또는 파일 없음).")
        return []
    try:
        rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("email_monitor.db 조회 오류: %s", error)
        return []
    finally:
        connection.close()


def _attach_analysis(rows):
    for row in rows:
        row["analysis"] = None
        raw = row.get("analysis_json")
        if raw:
            try:
                row["analysis"] = json.loads(raw)
            except (ValueError, TypeError):
                row["analysis"] = None
    return rows


def today_important_emails():
    today = today_kst_str()
    placeholders = ", ".join("?" * len(IMPORTANT_LEVELS))
    status_placeholders = ", ".join("?" * len(DONE_STATUSES))
    rows = _safe_query(
        f"""
        SELECT * FROM emails
        WHERE received_at LIKE ?
          AND importance IN ({placeholders})
          AND status IN ({status_placeholders})
        ORDER BY CASE importance WHEN 'urgent' THEN 0 ELSE 1 END, received_at DESC
        LIMIT 100
        """,
        (f"{today}%", *IMPORTANT_LEVELS, *DONE_STATUSES),
    )
    return _attach_analysis(rows)


def count_today_important_emails():
    today = today_kst_str()
    placeholders = ", ".join("?" * len(IMPORTANT_LEVELS))
    rows = _safe_query(
        f"SELECT COUNT(*) AS c FROM emails WHERE received_at LIKE ? AND importance IN ({placeholders})",
        (f"{today}%", *IMPORTANT_LEVELS),
    )
    return rows[0]["c"] if rows else 0


def count_today_urgent_emails():
    today = today_kst_str()
    rows = _safe_query(
        "SELECT COUNT(*) AS c FROM emails WHERE received_at LIKE ? AND importance = 'urgent'",
        (f"{today}%",),
    )
    return rows[0]["c"] if rows else 0


def count_yesterday_important_emails():
    placeholders = ", ".join("?" * len(IMPORTANT_LEVELS))
    rows = _safe_query(
        f"SELECT COUNT(*) AS c FROM emails WHERE date(received_at) = date('now', '-1 day') "
        f"AND importance IN ({placeholders})",
        IMPORTANT_LEVELS,
    )
    return rows[0]["c"] if rows else 0
