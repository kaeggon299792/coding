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
    db.close()
