import io
import sqlite3

import pytest

from services import localization_management as lms


def connection():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE dashboard_users (id INTEGER PRIMARY KEY);
        CREATE TABLE localization_strings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, language_key TEXT UNIQUE NOT NULL,
          source_text TEXT NOT NULL, source_hash TEXT UNIQUE NOT NULL,
          page_name TEXT NOT NULL, component TEXT NOT NULL, string_type TEXT NOT NULL,
          priority TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, deleted_at TEXT);
        CREATE TABLE localization_languages (
          language_code TEXT PRIMARY KEY, display_name TEXT NOT NULL,
          is_source INTEGER NOT NULL, is_active INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE localization_translations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, string_id INTEGER NOT NULL,
          language_code TEXT NOT NULL, translated_text TEXT, status TEXT NOT NULL,
          translated_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          last_translated_at TEXT, UNIQUE(string_id, language_code));
        CREATE TABLE localization_references (
          id INTEGER PRIMARY KEY AUTOINCREMENT, string_id INTEGER NOT NULL,
          source_kind TEXT NOT NULL, source_path TEXT NOT NULL, locator TEXT NOT NULL,
          last_seen_at TEXT NOT NULL, UNIQUE(string_id, source_kind, source_path, locator));
        CREATE TABLE localization_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, string_id INTEGER, event_type TEXT NOT NULL,
          language_code TEXT, actor_id INTEGER, detail TEXT, created_at TEXT NOT NULL);
        CREATE TABLE site_settings (
          setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL,
          updated_by INTEGER, updated_at TEXT NOT NULL);
        CREATE TABLE localization_glossary (
          id INTEGER PRIMARY KEY AUTOINCREMENT, source_text TEXT NOT NULL,
          target_text TEXT NOT NULL, language_code TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, updated_by INTEGER,
          UNIQUE(source_text, language_code));
        INSERT INTO localization_languages VALUES ('ko','한국어',1,1,'now');
        INSERT INTO localization_languages VALUES ('en','English',0,1,'now');
        """
    )
    return db


def test_deduplicates_source_and_tracks_all_references():
    db = connection()
    first = lms.register_string(db, "기업정보", page="Header", component="Menu",
                                source_kind="file", source_path="a.html", locator="line:1")
    second = lms.register_string(db, "기업정보", page="Footer", component="Link",
                                 source_kind="file", source_path="b.html", locator="line:2")
    assert first == second
    assert db.execute("SELECT COUNT(*) FROM localization_strings").fetchone()[0] == 1
    assert len(lms.references(db, first)) == 2
    assert db.execute("SELECT priority FROM localization_strings").fetchone()[0] == "Critical"


def test_translation_completion_and_qa_variable_check():
    db = connection()
    string_id = lms.register_string(db, "{name}님, 최근 공시 {count}건", page="Dashboard")
    lms.save_translation(db, string_id, "en", "Hello {name}")
    db.commit()
    summary = lms.dashboard_summary(db)
    assert summary["completed"] == 1
    assert summary["coverage"] == 100.0
    assert any(item["issue"] == "변수 누락 또는 변경" for item in lms.qa_report(db))


def test_csv_export_and_import_round_trip():
    db = connection()
    string_id = lms.register_string(db, "홈", page="Header", component="Menu")
    payload, mimetype = lms.export_file(db, "en", "csv")
    assert mimetype.startswith("text/csv")
    assert "language_key" in payload.decode("utf-8-sig")
    csv_payload = (
        "id,language_key,page_name,component,string_type,priority,korean,translation,status\n"
        f"{string_id},MENU_HOME,Header,Menu,Navigation,Critical,홈,Home,Completed\n"
    ).encode()
    upload = type("Upload", (), {"filename": "translations.csv", "read": lambda self, size: csv_payload})()
    result = lms.import_file(db, upload, "en")
    assert result == {"updated": 1, "errors": 0}
    assert db.execute("SELECT translated_text FROM localization_translations").fetchone()[0] == "Home"


def test_xlsx_export_is_valid_workbook():
    db = connection()
    lms.register_string(db, "로그인", page="Login", component="Button")
    payload, mimetype = lms.export_file(db, "en", "xlsx")
    assert payload.startswith(b"PK")
    assert "spreadsheetml" in mimetype


def test_ai_prompt_uses_glossary_style_and_splits_long_selection():
    db = connection()
    lms.save_glossary(db, "기업정보", "Company Profile", "en")
    ids = [
        lms.register_string(db, f"기업정보 번역 대상 {index} " + ("긴 문장 " * 120),
                            page="기업정보", component="Card")
        for index in range(3)
    ]
    chunks = lms.generate_translation_chunks(
        db, "en", ids, mode="prompt", style="business", max_items=1,
        max_chars=3000,
    )
    assert len(chunks) >= 2
    assert "카지노 산업 전문 번역가" in chunks[0]
    assert "기업정보 → Company Profile" in chunks[0]
    assert "전문적인 비즈니스 문체" in chunks[0]
    assert "ID=" in chunks[0] and "EN:" in chunks[0]


def test_ai_result_import_matches_language_key_and_rejects_unknown_ids():
    db = connection()
    first = lms.register_string(db, "홈", page="Header", component="Menu",
                                language_key="MENU_HOME")
    second = lms.register_string(db, "기업정보", page="Header", component="Menu",
                                 language_key="MENU_COMPANY")
    payload = """ID=MENU_HOME

EN:
Home

--------------------------------

ID=MENU_COMPANY

EN:
Company Profile

--------------------------------

ID=UNKNOWN

EN:
Unknown
"""
    result = lms.import_ai_translation_text(db, payload, "en")
    assert result == {"updated": 2, "errors": 1}
    assert db.execute(
        "SELECT translated_text FROM localization_translations WHERE string_id=?", (first,)
    ).fetchone()[0] == "Home"
    assert db.execute(
        "SELECT translated_text FROM localization_translations WHERE string_id=?", (second,)
    ).fetchone()[0] == "Company Profile"


def test_glossary_can_be_updated_and_deactivated():
    db = connection()
    lms.save_glossary(db, "리서치", "Research", "en")
    term = lms.list_glossary(db, "en")[0]
    lms.save_glossary(db, "리서치", "Industry Research", "en", glossary_id=term["id"])
    lms.deactivate_glossary(db, term["id"], "en")
    updated = lms.list_glossary(db, "en")[0]
    assert updated["target_text"] == "Industry Research"
    assert updated["is_active"] == 0


def test_schema_version_upgrade_creates_glossary_for_existing_database(tmp_path):
    from dashboard_db import schema

    db_path = tmp_path / "existing.db"
    db = schema.connect(str(db_path))
    db.execute("DROP TABLE localization_glossary")
    db.execute("PRAGMA user_version = 2026080401")
    db.commit(); db.close()

    upgraded = schema.connect(str(db_path))
    assert upgraded.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert upgraded.execute(
        "SELECT COUNT(*) FROM localization_glossary"
    ).fetchone()[0] == 8
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 2026080402
    upgraded.close()


def test_hourly_scan_runs_once_per_interval(tmp_path):
    db = connection()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "sample.html").write_text("<button>새 메뉴</button>", encoding="utf-8")
    first = lms.scan_if_due(db, tmp_path)
    second = lms.scan_if_due(db, tmp_path)
    assert first["files_scanned"] == 1
    assert second is None
    assert db.execute("SELECT COUNT(*) FROM localization_strings").fetchone()[0] == 1


def test_admin_routes_enforce_role_and_csrf(monkeypatch, tmp_path):
    import app as app_module
    from dashboard_db import schema

    db_path = tmp_path / "localization-routes.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    db = schema.connect(str(db_path))
    admin_id = db.execute(
        """INSERT INTO dashboard_users
               (username,password_hash,role,is_active,created_at)
           VALUES ('lms-admin','unused','admin',1,'2026-08-04T00:00:00')"""
    ).lastrowid
    user_id = db.execute(
        """INSERT INTO dashboard_users
               (username,password_hash,role,is_active,created_at)
           VALUES ('lms-user','unused','user',1,'2026-08-04T00:00:00')"""
    ).lastrowid
    string_id = lms.register_string(db, "로그인", page="Login", component="Button")
    db.commit(); db.close()
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        assert client.get("/admin/localization").status_code in {302, 401}
        with client.session_transaction() as browser_session:
            browser_session.update(user_id=user_id, username="lms-user", role="user")
        assert client.get("/admin/localization").status_code == 403
        with client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session.update(user_id=admin_id, username="lms-admin", role="admin",
                                   csrf_token="a" * 64)
        response = client.get("/admin/localization")
        assert response.status_code == 200
        assert "Localization Management" in response.get_data(as_text=True)
        assert "AI 번역 프롬프트 생성" in response.get_data(as_text=True)
        assert "<option selected>Pending</option>" in response.get_data(as_text=True)
        assert 'name="string_ids"' in response.get_data(as_text=True)
        assert 'name="string_ids" value=' in response.get_data(as_text=True)
        assert ' checked> AI 번역 대상 선택' in response.get_data(as_text=True)
        all_statuses = client.get("/admin/localization?status=")
        assert all_statuses.status_code == 200
        assert "<option selected>Pending</option>" not in all_statuses.get_data(as_text=True)
        route_db = schema.connect(str(db_path))
        pending_id = route_db.execute(
            """SELECT s.id FROM localization_strings s
               LEFT JOIN localization_translations t
                 ON t.string_id=s.id AND t.language_code='en'
               WHERE s.deleted_at IS NULL AND COALESCE(t.status,'Pending')='Pending'
               LIMIT 1"""
        ).fetchone()[0]
        route_db.close()
        assert client.post("/admin/localization/prompt", data={
            "csrf_token": "wrong", "language_code": "en",
            "string_ids": str(pending_id), "export_mode": "prompt",
        }).status_code == 400
        prompt = client.post("/admin/localization/prompt", data={
            "csrf_token": "a" * 64, "language_code": "en",
            "string_ids": str(pending_id), "export_mode": "prompt",
            "translation_style": "casino",
        })
        assert prompt.status_code == 200
        assert "카지노 산업 전문 번역가" in prompt.get_data(as_text=True)
        imported = client.post("/admin/localization/import-ai", data={
            "csrf_token": "a" * 64, "language_code": "en",
            "translation_payload": "ID=UI_" + "0" * 16 + "\n\nEN:\nIgnored",
        })
        assert imported.status_code == 302
        glossary_saved = client.post("/admin/localization/glossary", data={
            "csrf_token": "a" * 64, "language_code": "en",
            "source_text": "복합리조트", "target_text": "Integrated Resort",
        })
        assert glossary_saved.status_code == 302
        assert client.post(f"/admin/localization/{string_id}", data={
            "csrf_token": "wrong", "language_code": "en",
            "translated_text": "Login", "status": "Completed",
        }).status_code == 400
        saved = client.post(f"/admin/localization/{string_id}", data={
            "csrf_token": "a" * 64, "language_code": "en",
            "translated_text": "Login", "status": "Completed",
        })
        assert saved.status_code == 302

    db = schema.connect(str(db_path))
    assert db.execute(
        "SELECT translated_text FROM localization_translations WHERE string_id=?", (string_id,)
    ).fetchone()[0] == "Login"
    assert db.execute(
        "SELECT target_text FROM localization_glossary WHERE source_text='복합리조트'"
    ).fetchone()[0] == "Integrated Resort"
    db.close()
