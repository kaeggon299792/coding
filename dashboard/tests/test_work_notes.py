from datetime import datetime
from io import BytesIO

import pytest

from dashboard_db import schema
from services import work_notes


def _user(connection, username, role="admin"):
    return connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,membership_level,is_active,approval_status,created_at)
           VALUES (?,'unused',?,'black',1,'approved',datetime('now'))""",
        (username, role),
    ).lastrowid


def _clean(**overrides):
    raw = {
        "title": "월간회의 자료 작성",
        "content": "## 할 일\n- [ ] 매출표 확인",
        "work_date": "2026-08-07",
        "reminder_date": "2026-08-08",
        "reminder_time": "08:50",
        "target_date": "2026-08-10",
        "completed_at": "",
        "priority": "high",
        "status": "in_progress",
        "version_label": "1.0",
        "tags": "회의, 보고",
        "recurrence_type": "none",
        "recurrence_interval_days": "",
        "category_id": "",
        "is_pinned": "1",
    }
    raw.update(overrides)
    return work_notes.clean_form(raw)


def test_work_note_schema_and_dashboard_filters(tmp_path):
    connection = schema.connect(str(tmp_path / "work.db"))
    admin = _user(connection, "admin")
    note_id = work_notes.create_note(connection, admin, _clean())
    work_notes.create_note(
        connection, admin, _clean(
            title="대기 업무", status="waiting", priority="low",
            reminder_date="", target_date="2026-08-06", is_pinned="",
        )
    )
    connection.commit()

    counts = work_notes.dashboard_counts(connection, today="2026-08-07")
    rows = work_notes.list_notes(connection, {"status": "in_progress", "tag": "회의"})

    assert counts == {"in_progress": 1, "waiting": 1, "due_today": 0, "overdue": 1}
    assert [row["id"] for row in rows] == [note_id]
    assert rows[0]["tags"] == ["회의", "보고"]
    connection.close()


def test_completing_weekly_note_creates_next_occurrence_once(tmp_path):
    connection = schema.connect(str(tmp_path / "repeat.db"))
    admin = _user(connection, "admin")
    note_id = work_notes.create_note(
        connection, admin, _clean(
            recurrence_type="weekly", reminder_date="2026-08-08",
            target_date="2026-08-10",
        )
    )
    connection.commit()

    completed = _clean(
        recurrence_type="weekly", status="completed", completed_at="2026-08-11",
        reminder_date="2026-08-08", target_date="2026-08-10",
    )
    next_id = work_notes.update_note(connection, note_id, admin, completed)
    again = work_notes.update_note(connection, note_id, admin, completed)
    connection.commit()
    next_note = work_notes.get_note(connection, next_id)

    assert next_id is not None
    assert again is None
    assert next_note["status"] == "planned"
    assert next_note["work_date"] == "2026-08-14"
    assert next_note["target_date"] == "2026-08-17"
    assert next_note["reminder_date"] == "2026-08-15"
    connection.close()


def test_optional_dates_can_be_cleared_even_when_completed():
    cleaned = _clean(
        status="completed", reminder_date="", target_date="", completed_at=""
    )

    assert cleaned["reminder_at"] is None
    assert cleaned["target_date"] is None
    assert cleaned["completed_at"] is None


def test_reminder_message_marks_overdue_and_skips_completed(tmp_path):
    connection = schema.connect(str(tmp_path / "reminder.db"))
    admin = _user(connection, "admin")
    category = connection.execute(
        "SELECT id FROM work_note_categories WHERE name='월간회의'"
    ).fetchone()[0]
    due = _clean(
        category_id=str(category), reminder_date="2026-08-07",
        reminder_time="08:50", target_date="2026-08-04",
    )
    note_id = work_notes.create_note(connection, admin, due)
    work_notes.create_note(
        connection, admin, _clean(
            title="완료 업무", status="completed", completed_at="2026-08-06",
            reminder_date="2026-08-07", reminder_time="08:50",
        )
    )
    connection.commit()
    sent = []

    result = work_notes.send_due_reminders(
        connection,
        current=datetime.fromisoformat("2026-08-07T08:51:00+09:00"),
        sender=lambda message, force=False: sent.append((message, force)) or True,
    )

    assert result == {"sent": 1, "failed": 0}
    assert "🔴 3일 지연" in sent[0][0]
    assert "[높음] 월간회의 자료 작성" in sent[0][0]
    assert "업무노트에서 확인 →" in sent[0][0]
    assert sent[0][1] is True
    assert work_notes.get_note(connection, note_id)["last_reminded_at"] is not None
    connection.close()


@pytest.fixture
def work_note_client(monkeypatch, tmp_path):
    import app as app_module
    import config

    db_path = tmp_path / "routes.db"
    file_dir = tmp_path / "work-files"
    monkeypatch.setattr(config, "DASHBOARD_DB_FILE", str(db_path))
    monkeypatch.setattr(config, "WORK_NOTE_FILE_DIR", str(file_dir))
    app_module.app.config.update(TESTING=True)
    connection = schema.connect(str(db_path))
    admin = _user(connection, "route-admin")
    user = _user(connection, "route-user", "user")
    connection.commit()
    connection.close()
    return app_module.app.test_client(), db_path, file_dir, admin, user


def _login(client, user_id, role, token):
    with client.session_transaction() as session:
        session.update(
            user_id=user_id, username=f"route-{role}", role=role, csrf_token=token
        )


def test_work_note_routes_are_admin_only_and_render_timeline(work_note_client):
    client, _, _, admin, user = work_note_client
    assert client.get("/blog/work-notes").status_code == 302
    _login(client, user, "user", "u" * 64)
    assert client.get("/blog/work-notes").status_code == 403
    _login(client, admin, "admin", "a" * 64)
    response = client.get("/blog/work-notes")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "업무노트" in html
    assert "work-note-dashboard" in html
    assert "갤러리" not in html


def test_admin_creates_note_with_protected_attachment_and_markdown_preview(work_note_client):
    client, db_path, _, admin, user = work_note_client
    _login(client, admin, "admin", "a" * 64)
    response = client.post(
        "/blog/work-notes/new",
        data={
            "csrf_token": "a" * 64,
            "title": "첨부 업무", "content": "- [ ] 확인", "work_date": "2026-08-07",
            "priority": "normal", "status": "planned", "recurrence_type": "none",
            "attachments": (BytesIO(b"hello"), "check.txt"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    connection = schema.connect(str(db_path))
    attachment = connection.execute(
        "SELECT id FROM work_note_attachments WHERE original_name='check.txt'"
    ).fetchone()
    note = connection.execute("SELECT id FROM work_notes WHERE title='첨부 업무'").fetchone()
    connection.close()
    assert attachment and note
    assert client.get(f"/blog/work-notes/files/{attachment['id']}").status_code == 200
    preview = client.post(
        "/blog/work-notes/preview",
        data={"csrf_token": "a" * 64, "content": "- [x] 완료"},
    )
    assert 'type="checkbox"' in preview.get_json()["html"]

    _login(client, user, "user", "u" * 64)
    assert client.get(f"/blog/work-notes/files/{attachment['id']}").status_code == 403


def test_work_note_editor_has_required_tools_and_two_minute_autosave():
    from pathlib import Path

    root = Path(__file__).parents[1]
    template = (root / "templates" / "work_notes" / "form.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "work-notes.js").read_text(encoding="utf-8")
    for tool in ("heading", "bold", "list", "check", "table", "quote", "link", "code"):
        assert f'data-md="{tool}"' in template
    assert "data-image-upload-for" in template
    assert "120000" in script
    assert "localStorage.setItem" in script
