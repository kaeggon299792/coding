"""Database and reminder operations for the administrator-only work-note board."""

from __future__ import annotations

import calendar
import html
import json
import re
import sqlite3
from datetime import date, datetime, timedelta

import config
from services import telegram_alert
from utils import now_kst


STATUSES = {
    "planned": "시작 전",
    "in_progress": "진행 중",
    "waiting": "대기",
    "on_hold": "보류",
    "completed": "완료",
}
PRIORITIES = {
    "urgent": "긴급",
    "high": "높음",
    "normal": "보통",
    "low": "낮음",
}
RECURRENCES = {
    "none": "없음",
    "weekly": "매주",
    "monthly": "매월",
    "custom": "사용자 지정",
}
SORTS = {
    "created_desc": "n.is_pinned DESC, n.created_at DESC, n.id DESC",
    "work_date_desc": "n.is_pinned DESC, n.work_date DESC, n.id DESC",
    "target_asc": "n.is_pinned DESC, n.target_date IS NULL, n.target_date, n.id DESC",
    "priority_desc": "n.is_pinned DESC, CASE n.priority WHEN 'urgent' THEN 4 WHEN 'high' THEN 3 WHEN 'normal' THEN 2 ELSE 1 END DESC, n.target_date IS NULL, n.target_date",
    "status": "n.is_pinned DESC, CASE n.status WHEN 'planned' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'waiting' THEN 3 WHEN 'on_hold' THEN 4 ELSE 5 END, n.target_date IS NULL, n.target_date",
}
_IMAGE_URL_RE = re.compile(r"/blog/work-notes/files/(\d+)")


def parse_tags(raw_value):
    tags = []
    seen = set()
    for raw_tag in re.split(r"[,\n]", raw_value or ""):
        tag = re.sub(r"\s+", " ", raw_tag.strip().lstrip("#")).strip()
        if not tag:
            continue
        if len(tag) > 20:
            raise ValueError("태그는 각각 20자 이하로 입력해주세요.")
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    if len(tags) > 10:
        raise ValueError("태그는 최대 10개까지 입력할 수 있습니다.")
    return tags


def _date(value, label, required=False):
    value = (value or "").strip()
    if not value:
        if required:
            raise ValueError(f"{label}을 선택해주세요.")
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(f"{label} 형식이 올바르지 않습니다.") from error


def clean_form(source):
    title = (source.get("title") or "").strip()
    content = (source.get("content") or "").strip()
    if not title or len(title) > 150:
        raise ValueError("제목은 1~150자로 입력해주세요.")
    if not content or len(content) > 50_000:
        raise ValueError("내용은 1~50,000자로 입력해주세요.")
    status = (source.get("status") or "planned").strip()
    priority = (source.get("priority") or "normal").strip()
    recurrence_type = (source.get("recurrence_type") or "none").strip()
    if status not in STATUSES:
        raise ValueError("상태를 선택해주세요.")
    if priority not in PRIORITIES:
        raise ValueError("중요도를 선택해주세요.")
    if recurrence_type not in RECURRENCES:
        raise ValueError("반복 방식을 선택해주세요.")
    reminder_date = _date(source.get("reminder_date"), "알림일")
    reminder_time = (source.get("reminder_time") or "08:50").strip()
    reminder_at = None
    if reminder_date:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", reminder_time):
            raise ValueError("알림 시간을 올바르게 입력해주세요.")
        reminder_at = f"{reminder_date}T{reminder_time}:00+09:00"
    completed_at = _date(source.get("completed_at"), "완료일")
    interval = None
    if recurrence_type == "custom":
        try:
            interval = int(source.get("recurrence_interval_days") or 0)
        except (TypeError, ValueError) as error:
            raise ValueError("사용자 지정 반복 주기를 입력해주세요.") from error
        if not 1 <= interval <= 365:
            raise ValueError("사용자 지정 반복 주기는 1~365일이어야 합니다.")
    category_raw = (source.get("category_id") or "").strip()
    category_id = int(category_raw) if category_raw.isdigit() else None
    return {
        "category_id": category_id,
        "title": title,
        "content": content,
        "work_date": _date(source.get("work_date"), "작성일", required=True),
        "reminder_at": reminder_at,
        "target_date": _date(source.get("target_date"), "완료목표일"),
        "completed_at": completed_at,
        "priority": priority,
        "status": status,
        "version_label": (source.get("version_label") or "").strip()[:40] or None,
        "tags": parse_tags(source.get("tags")),
        "is_pinned": (source.get("is_pinned") or "") in {"1", "on", "true"},
        "recurrence_type": recurrence_type,
        "recurrence_interval_days": interval,
    }


def list_categories(connection, include_inactive=False):
    where = "" if include_inactive else "WHERE is_active=1"
    return [dict(row) for row in connection.execute(
        f"SELECT * FROM work_note_categories {where} ORDER BY sort_order, name"
    ).fetchall()]


def create_category(connection, name, emoji="📁"):
    name = re.sub(r"\s+", " ", (name or "").strip())
    emoji = (emoji or "📁").strip()[:8] or "📁"
    if not name or len(name) > 40:
        raise ValueError("카테고리명은 1~40자로 입력해주세요.")
    now = now_kst().isoformat(timespec="seconds")
    order = connection.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 10 FROM work_note_categories"
    ).fetchone()[0]
    try:
        cursor = connection.execute(
            """INSERT INTO work_note_categories
               (name,emoji,is_active,sort_order,created_at,updated_at)
               VALUES (?,?,1,?,?,?)""", (name, emoji, order, now, now)
        )
    except Exception as error:
        if "UNIQUE" in str(error).upper():
            raise ValueError("이미 존재하는 카테고리입니다.") from error
        raise
    return cursor.lastrowid


def update_category(connection, category_id, name, emoji, is_active=True):
    name = re.sub(r"\s+", " ", (name or "").strip())
    emoji = (emoji or "📁").strip()[:8] or "📁"
    if not name or len(name) > 40:
        raise ValueError("카테고리명은 1~40자로 입력해주세요.")
    try:
        cursor = connection.execute(
            """UPDATE work_note_categories SET name=?,emoji=?,is_active=?,updated_at=?
               WHERE id=?""",
            (name, emoji, 1 if is_active else 0, now_kst().isoformat(timespec="seconds"), category_id),
        )
    except sqlite3.IntegrityError as error:
        raise ValueError("이미 존재하는 카테고리입니다.") from error
    if not cursor.rowcount:
        raise ValueError("카테고리를 찾을 수 없습니다.")


def _decode_note(row):
    item = dict(row)
    try:
        item["tags"] = json.loads(item.get("tags_json") or "[]")
    except (TypeError, ValueError):
        item["tags"] = []
    reminder = item.get("reminder_at") or ""
    item["reminder_date"] = reminder[:10] if reminder else ""
    item["reminder_time"] = reminder[11:16] if reminder else "08:50"
    return item


def dashboard_counts(connection, today=None, owner_id=None):
    today = today or now_kst().date().isoformat()
    owner_clause = " AND author_id=?" if owner_id is not None else ""
    params = [today, today]
    if owner_id is not None:
        params.append(int(owner_id))
    row = connection.execute(
        """SELECT
             SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) AS in_progress,
             SUM(CASE WHEN status='waiting' THEN 1 ELSE 0 END) AS waiting,
             SUM(CASE WHEN status<>'completed' AND target_date=? THEN 1 ELSE 0 END) AS due_today,
             SUM(CASE WHEN status<>'completed' AND target_date<? THEN 1 ELSE 0 END) AS overdue
           FROM work_notes WHERE is_deleted=0""" + owner_clause, params
    ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def _note_filter_sql(filters, owner_id=None):
    clauses = ["n.is_deleted=0"]
    params = []
    if owner_id is not None:
        clauses.append("n.author_id=?")
        params.append(int(owner_id))
    status = (filters.get("status") or "").strip()
    if status in STATUSES:
        clauses.append("n.status=?")
        params.append(status)
    category_id = str(filters.get("category_id") or "").strip()
    if category_id.isdigit():
        clauses.append("n.category_id=?")
        params.append(int(category_id))
    term = (filters.get("q") or "").strip()
    if term:
        like = f"%{term[:100]}%"
        clauses.append("(n.title LIKE ? OR n.content LIKE ? OR n.tags_json LIKE ? OR n.version_label LIKE ?)")
        params.extend([like] * 4)
    tag = (filters.get("tag") or "").strip().lstrip("#")[:20]
    if tag:
        clauses.append("n.tags_json LIKE ?")
        params.append(f'%"{tag}"%')
    return clauses, params


def list_notes(connection, filters, limit=20, offset=0, owner_id=None):
    clauses, params = _note_filter_sql(filters, owner_id)
    sort = filters.get("sort") if filters.get("sort") in SORTS else "created_desc"
    params.extend([max(1, min(int(limit), 100)), max(0, int(offset))])
    rows = connection.execute(
        f"""SELECT n.*,c.name AS category_name,c.emoji AS category_emoji
            FROM work_notes n LEFT JOIN work_note_categories c ON c.id=n.category_id
            WHERE {' AND '.join(clauses)} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?""",
        params,
    ).fetchall()
    return [_decode_note(row) for row in rows]


def count_notes(connection, filters, owner_id=None):
    clauses, params = _note_filter_sql(filters, owner_id)
    return connection.execute(
        f"SELECT COUNT(*) FROM work_notes n WHERE {' AND '.join(clauses)}", params
    ).fetchone()[0]


def available_tags(connection, owner_id=None):
    tags = set()
    sql = "SELECT tags_json FROM work_notes WHERE is_deleted=0"
    params = []
    if owner_id is not None:
        sql += " AND author_id=?"
        params.append(int(owner_id))
    for row in connection.execute(sql, params).fetchall():
        try:
            tags.update(json.loads(row["tags_json"] or "[]"))
        except (TypeError, ValueError):
            pass
    return sorted(tags, key=str.casefold)


def create_note(connection, author_id, data, recurrence_parent_id=None):
    now = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """INSERT INTO work_notes
           (author_id,category_id,title,content,work_date,reminder_at,target_date,
            completed_at,priority,status,version_label,tags_json,is_pinned,
            recurrence_type,recurrence_interval_days,recurrence_parent_id,
            created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (author_id, data["category_id"], data["title"], data["content"],
         data["work_date"], data["reminder_at"], data["target_date"],
         data["completed_at"], data["priority"], data["status"],
         data["version_label"], json.dumps(data["tags"], ensure_ascii=False),
         1 if data["is_pinned"] else 0, data["recurrence_type"],
         data["recurrence_interval_days"], recurrence_parent_id, now, now),
    )
    return cursor.lastrowid


def get_note(connection, note_id, owner_id=None):
    owner_clause = " AND n.author_id=?" if owner_id is not None else ""
    params = [note_id]
    if owner_id is not None:
        params.append(int(owner_id))
    row = connection.execute(
        """SELECT n.*,c.name AS category_name,c.emoji AS category_emoji
           FROM work_notes n LEFT JOIN work_note_categories c ON c.id=n.category_id
           WHERE n.id=? AND n.is_deleted=0""" + owner_clause, params
    ).fetchone()
    if not row:
        return None
    item = _decode_note(row)
    item["attachments"] = [dict(value) for value in connection.execute(
        """SELECT * FROM work_note_attachments
           WHERE note_id=? AND is_deleted=0 ORDER BY created_at,id""", (note_id,)
    ).fetchall()]
    return item


def _advance(value, recurrence_type, interval_days=None):
    if not value:
        return None
    current = date.fromisoformat(value)
    if recurrence_type == "weekly":
        return (current + timedelta(days=7)).isoformat()
    if recurrence_type == "custom":
        return (current + timedelta(days=interval_days or 1)).isoformat()
    if recurrence_type == "monthly":
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return date(year, month, day).isoformat()
    return value


def _create_next_recurrence(connection, note, author_id):
    recurrence = note["recurrence_type"]
    if recurrence == "none":
        return None
    data = {
        key: note.get(key) for key in (
            "category_id", "title", "content", "priority", "version_label",
            "recurrence_type", "recurrence_interval_days",
        )
    }
    data.update({
        "work_date": _advance(note["work_date"], recurrence, note.get("recurrence_interval_days")),
        "target_date": _advance(note.get("target_date"), recurrence, note.get("recurrence_interval_days")),
        "completed_at": None,
        "status": "planned",
        "tags": note.get("tags") or [],
        "is_pinned": note.get("is_pinned", False),
    })
    reminder_date = _advance(note.get("reminder_date"), recurrence, note.get("recurrence_interval_days"))
    data["reminder_at"] = f"{reminder_date}T{note.get('reminder_time') or '08:50'}:00+09:00" if reminder_date else None
    return create_note(connection, author_id, data, recurrence_parent_id=note["id"])


def update_note(connection, note_id, author_id, data):
    previous = get_note(connection, note_id)
    if not previous:
        raise ValueError("업무노트를 찾을 수 없습니다.")
    cursor = connection.execute(
        """UPDATE work_notes SET category_id=?,title=?,content=?,work_date=?,
           reminder_at=?,target_date=?,completed_at=?,priority=?,status=?,
           version_label=?,tags_json=?,is_pinned=?,recurrence_type=?,
           recurrence_interval_days=?,
           last_reminded_at=CASE WHEN reminder_at IS ? THEN last_reminded_at ELSE NULL END,
           updated_at=?
           WHERE id=? AND is_deleted=0""",
        (data["category_id"], data["title"], data["content"], data["work_date"],
         data["reminder_at"], data["target_date"], data["completed_at"],
         data["priority"], data["status"], data["version_label"],
         json.dumps(data["tags"], ensure_ascii=False), 1 if data["is_pinned"] else 0,
         data["recurrence_type"], data["recurrence_interval_days"], data["reminder_at"],
         now_kst().isoformat(timespec="seconds"), note_id),
    )
    if not cursor.rowcount:
        raise ValueError("업무노트를 찾을 수 없습니다.")
    next_id = None
    if previous["status"] != "completed" and data["status"] == "completed":
        updated = get_note(connection, note_id)
        duplicate = connection.execute(
            "SELECT id FROM work_notes WHERE recurrence_parent_id=? AND is_deleted=0",
            (note_id,),
        ).fetchone()
        if not duplicate:
            next_id = _create_next_recurrence(connection, updated, author_id)
    return next_id


def toggle_pin(connection, note_id):
    cursor = connection.execute(
        """UPDATE work_notes SET is_pinned=CASE is_pinned WHEN 1 THEN 0 ELSE 1 END,
           updated_at=? WHERE id=? AND is_deleted=0""",
        (now_kst().isoformat(timespec="seconds"), note_id),
    )
    if not cursor.rowcount:
        raise ValueError("업무노트를 찾을 수 없습니다.")


def delete_note(connection, note_id):
    now = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        "UPDATE work_notes SET is_deleted=1,deleted_at=?,updated_at=? WHERE id=? AND is_deleted=0",
        (now, now, note_id),
    )
    if not cursor.rowcount:
        raise ValueError("업무노트를 찾을 수 없습니다.")


def register_attachment(connection, owner_id, stored_name, original_name, content_type, file_size, kind="file", note_id=None):
    cursor = connection.execute(
        """INSERT INTO work_note_attachments
           (note_id,owner_id,stored_name,original_name,content_type,file_size,kind,created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (note_id, owner_id, stored_name, original_name, content_type, file_size,
         kind, now_kst().isoformat(timespec="seconds")),
    )
    return cursor.lastrowid


def attach_inline_images(connection, note_id, content, owner_id):
    ids = {int(value) for value in _IMAGE_URL_RE.findall(content or "")}
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    connection.execute(
        f"""UPDATE work_note_attachments SET note_id=?
            WHERE id IN ({placeholders}) AND owner_id=? AND kind='image'
              AND is_deleted=0 AND (note_id IS NULL OR note_id=?)""",
        (note_id, *ids, owner_id, note_id),
    )


def get_attachment(connection, attachment_id, owner_id=None):
    owner_clause = " AND owner_id=?" if owner_id is not None else ""
    params = [attachment_id]
    if owner_id is not None:
        params.append(int(owner_id))
    row = connection.execute(
        "SELECT * FROM work_note_attachments WHERE id=? AND is_deleted=0" + owner_clause,
        params,
    ).fetchone()
    return dict(row) if row else None


def soft_delete_attachment(connection, attachment_id):
    cursor = connection.execute(
        "UPDATE work_note_attachments SET is_deleted=1,deleted_at=? WHERE id=? AND is_deleted=0",
        (now_kst().isoformat(timespec="seconds"), attachment_id),
    )
    if not cursor.rowcount:
        raise ValueError("첨부파일을 찾을 수 없습니다.")


def due_reminders(connection, current=None):
    current = current or now_kst()
    rows = connection.execute(
        """SELECT n.*,c.name AS category_name FROM work_notes n
           LEFT JOIN work_note_categories c ON c.id=n.category_id
           JOIN dashboard_users u ON u.id=n.author_id AND u.role='admin'
           WHERE n.is_deleted=0 AND n.status<>'completed' AND n.reminder_at IS NOT NULL
             AND n.reminder_at<=? AND n.last_reminded_at IS NULL
           ORDER BY n.reminder_at,n.id""",
        (current.isoformat(timespec="seconds"),),
    ).fetchall()
    return [_decode_note(row) for row in rows]


def reminder_message(note, today=None):
    today = today or now_kst().date()
    priority = PRIORITIES.get(note["priority"], note["priority"])
    status = STATUSES.get(note["status"], note["status"])
    target = note.get("target_date") or "미설정"
    overdue = ""
    if note.get("target_date") and note["status"] != "completed":
        days = (today - date.fromisoformat(note["target_date"])).days
        if days > 0:
            overdue = f"\n🔴 {days}일 지연"
    url = f"{config.DASHBOARD_PUBLIC_URL.rstrip('/')}/blog/work-notes/{note['id']}"
    return (
        "📌 <b>업무 알림</b>\n"
        f"[{html.escape(priority)}] {html.escape(note['title'])}\n\n"
        f"상태: {html.escape(status)}\n"
        f"카테고리: {html.escape(note.get('category_name') or '미분류')}\n"
        f"목표일: {html.escape(target)}{overdue}\n\n"
        f'<a href="{html.escape(url, quote=True)}">업무노트에서 확인 →</a>'
    )


def send_due_reminders(connection, current=None, sender=None):
    current = current or now_kst()
    sender = sender or telegram_alert.send_alert
    sent = 0
    failed = 0
    for note in due_reminders(connection, current):
        if sender(reminder_message(note, current.date()), force=True):
            connection.execute(
                "UPDATE work_notes SET last_reminded_at=?,updated_at=? WHERE id=?",
                (current.isoformat(timespec="seconds"), current.isoformat(timespec="seconds"), note["id"]),
            )
            sent += 1
        else:
            failed += 1
    connection.commit()
    return {"sent": sent, "failed": failed}
