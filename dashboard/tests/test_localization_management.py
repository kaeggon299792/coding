import io
import sqlite3
import sys
from pathlib import Path

import pytest

from services import localization_management as lms

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from import_localization_translations import FileUpload


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
        INSERT INTO localization_languages VALUES ('ja','日本語',0,1,'now');
        INSERT INTO localization_languages VALUES ('yue-HK','廣東話',0,1,'now');
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


def test_file_import_promotes_translated_pending_rows_and_skips_empty_rows():
    db = connection()
    translated_id = lms.register_string(db, "기업정보", language_key="MENU_COMPANY")
    empty_id = lms.register_string(db, "뉴스", language_key="MENU_NEWS")
    csv_payload = (
        "id,language_key,en,status\n"
        f"{translated_id},MENU_COMPANY,Company Profile,Pending\n"
        f"{empty_id},MENU_NEWS,,Pending\n"
    ).encode()
    upload = type("Upload", (), {
        "filename": "translations.csv",
        "read": lambda self, size: csv_payload,
    })()
    result = lms.import_file(db, upload, "en")
    assert result == {"updated": 1, "errors": 1}
    row = db.execute(
        "SELECT translated_text,status FROM localization_translations WHERE string_id=?",
        (translated_id,),
    ).fetchone()
    assert tuple(row) == ("Company Profile", "Completed")
    assert db.execute(
        "SELECT 1 FROM localization_translations WHERE string_id=?", (empty_id,)
    ).fetchone() is None


def test_localization_import_file_upload_obeys_read_limit(tmp_path):
    csv_path = tmp_path / "translations.csv"
    csv_path.write_bytes(b"abcdef")
    upload = FileUpload(csv_path)
    assert upload.filename == "translations.csv"
    assert upload.read(3) == b"abc"


def test_xlsx_export_is_valid_workbook():
    db = connection()
    lms.register_string(db, "로그인", page="Login", component="Button")
    payload, mimetype = lms.export_file(db, "en", "xlsx")
    assert payload.startswith(b"PK")
    assert "spreadsheetml" in mimetype


def test_prompt_windows_use_compact_scrollable_height():
    from pathlib import Path

    css = (Path(__file__).parents[1] / "static" / "css" / "dashboard.css").read_text(
        encoding="utf-8"
    )
    assert ".localization-prompt-chunk pre{width:100%;height:320px;max-height:320px" in css
    assert ".localization-prompt-pair textarea{height:320px;min-height:320px" in css


def test_japanese_and_cantonese_pages_load_matching_noto_webfonts():
    from pathlib import Path

    root = Path(__file__).parents[1]
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert "@fontsource-variable/noto-sans-jp@5.3.0/index.css" in base
    assert "@fontsource-variable/noto-sans-hk@5.3.0/index.css" in base
    assert "{% if current_locale == 'ja' %}" in base
    assert "{% elif current_locale == 'yue-HK' %}" in base
    assert "html:lang(ja)" in css
    assert "'Noto Sans JP Variable'" in css
    assert "html:lang(yue-HK)" in css
    assert "'Noto Sans HK Variable'" in css


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
    assert "하나의 ```text 코드블록" in chunks[0]
    assert "코드블록 밖에는" in chunks[0]


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


@pytest.mark.parametrize(
    ("language_code", "target_name", "output_label", "translated"),
    (
        ("ja", "일본어", "JA", "ホーム"),
        ("yue-HK", "광둥어(홍콩 번체)", "YUE", "首頁"),
    ),
)
def test_prompt_and_import_use_selected_target_language(
    language_code, target_name, output_label, translated
):
    db = connection()
    string_id = lms.register_string(
        db, "홈", page="Header", component="Menu", language_key="MENU_HOME"
    )
    chunks = lms.generate_translation_chunks(
        db, language_code, [string_id], mode="prompt", style="natural"
    )
    assert f"자연스러운 {target_name}로 번역하세요" in chunks[0]
    assert f"\n{output_label}:\n" in chunks[0]
    assert "\nEN:\n" not in chunks[0]

    result = lms.import_ai_translation_text(
        db, f"ID=MENU_HOME\n\n{output_label}:\n{translated}", language_code
    )
    assert result == {"updated": 1, "errors": 0}
    saved = db.execute(
        """SELECT translated_text FROM localization_translations
           WHERE string_id=? AND language_code=?""",
        (string_id, language_code),
    ).fetchone()[0]
    assert saved == translated


def test_japanese_import_does_not_accept_english_output_label():
    db = connection()
    string_id = lms.register_string(
        db, "홈", page="Header", component="Menu", language_key="MENU_HOME"
    )
    result = lms.import_ai_translation_text(db, "ID=MENU_HOME\n\nEN:\nHome", "ja")
    assert result == {"updated": 0, "errors": 1}
    assert db.execute(
        """SELECT COUNT(*) FROM localization_translations
           WHERE string_id=? AND language_code='ja'""",
        (string_id,),
    ).fetchone()[0] == 0


def test_glossary_can_be_updated_and_deactivated():
    db = connection()
    lms.save_glossary(db, "리서치", "Research", "en")
    term = lms.list_glossary(db, "en")[0]
    lms.save_glossary(db, "리서치", "Industry Research", "en", glossary_id=term["id"])
    lms.deactivate_glossary(db, term["id"], "en")
    updated = lms.list_glossary(db, "en")[0]
    assert updated["target_text"] == "Industry Research"
    assert updated["is_active"] == 0


def test_glossary_rejects_duplicate_source_for_same_language():
    db = connection()
    lms.save_glossary(db, "복합리조트", "Integrated Resort", "en")
    with pytest.raises(ValueError, match="이미 등록된"):
        lms.save_glossary(db, "복합리조트", "IR", "en")


def test_all_language_prompt_and_import_use_one_combined_clipboard_payload():
    db = connection()
    string_id = lms.register_string(
        db, "기업정보", page="Header", component="Menu",
        language_key="MENU_COMPANY_ALL",
    )
    chunks = lms.generate_all_translation_chunks(
        db, [string_id], mode="prompt", style="business"
    )
    assert len(chunks) == 1
    assert chunks[0].count("ID=MENU_COMPANY_ALL") == 1
    for label in ("EN:", "JA:", "YUE:"):
        assert label in chunks[0]

    result = lms.import_ai_translation_text_all(
        db,
        """ID=MENU_COMPANY_ALL

EN:
Company Information
JA:
企業情報
YUE:
公司資料""",
    )
    assert result == {
        "updated": 3,
        "errors": 0,
        "languages": {"en": 1, "ja": 1, "yue-HK": 1},
    }
    rows = db.execute(
        """SELECT language_code, translated_text FROM localization_translations
           WHERE string_id=? ORDER BY language_code""",
        (string_id,),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("en", "Company Information"),
        ("ja", "企業情報"),
        ("yue-HK", "公司資料"),
    ]
    assert lms.detect_ai_translation_languages(db, "JA:\n企業情報") == {"ja"}
    assert lms.detect_ai_translation_languages(
        db, "EN:\nCompany\nJA:\n企業\nYUE:\n公司"
    ) == {"en", "ja", "yue-HK"}


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
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
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


def test_scan_excludes_admin_templates_and_explicit_ignore_blocks(tmp_path):
    db = connection()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "user_management.html").write_text(
        "<h1>관리자 계정 관리</h1>", encoding="utf-8"
    )
    (templates / "public.html").write_text(
        '<p>공개 안내</p><a data-i18n-ignore>번역 필요 3건</a>',
        encoding="utf-8",
    )
    lms.scan_project(db, tmp_path)
    sources = {
        row[0] for row in db.execute("SELECT source_text FROM localization_strings")
    }
    assert "공개 안내" in sources
    assert "관리자 계정 관리" not in sources
    assert "번역 필요 3건" not in sources


def test_scan_registers_public_news_database_content(monkeypatch, tmp_path):
    db = connection()
    (tmp_path / "templates").mkdir()
    monkeypatch.setattr(
        "services.news_reader.localization_content_rows",
        lambda: [
            {"source_id": 10, "source_text": "카지노 규제 개편", "field": "category",
             "component": "News Category"},
            {"source_id": 11, "source_text": "관광산업 주요 뉴스", "field": "title",
             "component": "News Article"},
            {"source_id": 12, "source_text": "시장 영향 분석", "field": "latest_summary",
             "component": "AI Analysis"},
        ],
    )

    lms.scan_project(db, tmp_path)

    rows = db.execute(
        """SELECT s.source_text, r.source_kind, r.source_path, r.locator
           FROM localization_strings s
           JOIN localization_references r ON r.string_id=s.id
           WHERE r.source_kind='external_database'
           ORDER BY s.source_text"""
    ).fetchall()
    assert {(row[0], row[2], row[3]) for row in rows} == {
        ("카지노 규제 개편", "news_history:10", "category"),
        ("관광산업 주요 뉴스", "news_history:11", "title"),
        ("시장 영향 분석", "news_history:12", "latest_summary"),
    }


def test_dynamic_values_flattens_company_profile_json_lists():
    values = list(lms._dynamic_values(
        '["파라다이스시티", {"risk": "외국인 수요 변동"}]'
    ))
    assert values == ["파라다이스시티", "외국인 수요 변동"]


def test_register_rendered_strings_deduplicates_public_copy():
    db = connection()
    first = lms.register_rendered_strings(
        db, ["관광진흥법", "관광진흥법"],
        page="laws_page", source_path="/en/laws",
    )
    second = lms.register_rendered_strings(
        db, ["관광진흥법"], page="laws_page", source_path="/en/laws",
    )
    assert first == 2
    assert second == 1
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
        assert client.get("/admin/localization/work").status_code in {302, 401}
        with client.session_transaction() as browser_session:
            browser_session.update(user_id=user_id, username="lms-user", role="user")
        assert client.get("/admin/localization").status_code == 403
        assert client.get("/admin/localization/work").status_code == 403
        with client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session.update(user_id=admin_id, username="lms-admin", role="admin",
                                   csrf_token="a" * 64)
        response = client.get("/admin/localization")
        assert response.status_code == 200
        page_html = response.get_data(as_text=True)
        assert "Localization Management" in page_html
        assert "20260805-admin4" in page_html
        assert "전체 번역 필요" in page_html
        assert "전체 번역 필요" not in client.get("/").get_data(as_text=True)
        assert '<option value="en" selected' in page_html
        assert "AI 번역 프롬프트 생성" in page_html
        assert '<option value="all" selected>전체 언어 한 번에</option>' in page_html
        assert '<option value="all" selected>전체 언어</option>' in page_html
        assert "<option selected>Pending</option>" in page_html
        assert 'name="string_ids"' in page_html
        assert 'name="string_ids" value=' in page_html
        assert ' checked> AI 번역 대상 선택' in page_html
        assert '<details class="localization-results">' in page_html
        assert '<details class="panel localization-item">' in page_html
        assert "Work 자동화 화면" in page_html
        work_page = client.get("/admin/localization/work?language=en&limit=150")
        assert work_page.status_code == 200
        work_html = work_page.get_data(as_text=True)
        assert "Localization Work" in work_html
        assert "현재 대기 묶음 불러오기" in work_html
        assert "이 묶음 클립보드 복사" in work_html
        assert 'name="translation_payload"' in work_html
        assert 'name="return_to" value="work"' in work_html
        assert '<option value="50" selected>50개</option>' in work_html
        assert '<option value="100"' not in work_html
        assert 'name="limit" value="50"' in work_html
        assert client.post("/admin/localization/import-ai", data={
            "csrf_token": "wrong", "language_code": "en", "return_to": "work",
            "translation_payload": "ID=MENU_HOME\n\nEN:\nHome",
        }).status_code == 400
        work_import = client.post("/admin/localization/import-ai", data={
            "csrf_token": "a" * 64, "language_code": "en", "return_to": "work",
            "limit": "150", "translation_payload": "ID=UNKNOWN_KEY\n\nEN:\nHome",
        }, follow_redirects=False)
        assert work_import.status_code == 302
        assert "/admin/localization/work?" in work_import.headers["Location"]
        assert "language=en" in work_import.headers["Location"]
        assert "limit=50" in work_import.headers["Location"]
        all_languages = client.get("/admin/localization?language=all&status=Pending")
        assert all_languages.status_code == 200
        all_languages_html = all_languages.get_data(as_text=True)
        assert '<option value="all" selected>전체 언어</option>' in all_languages_html
        assert "English (en)" in all_languages_html
        assert "日本語 (ja)" in all_languages_html
        assert "廣東話 (yue-HK)" in all_languages_html
        assert 'name="language_code" value="all"' not in all_languages_html
        all_statuses = client.get("/admin/localization?status=")
        assert all_statuses.status_code == 200
        status_filter = all_statuses.get_data(as_text=True).split(
            '<select name="status" aria-label="상태">', 1
        )[1].split("</select>", 1)[0]
        assert "<option selected>Pending</option>" not in status_filter
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
        assert 'name="translation_chunk"' in prompt.get_data(as_text=True)
        all_prompt = client.post("/admin/localization/prompt", data={
            "csrf_token": "a" * 64, "language_code": "all",
            "return_language_code": "en", "string_ids": str(pending_id),
            "export_mode": "prompt", "translation_style": "business",
        })
        assert all_prompt.status_code == 200
        all_prompt_html = all_prompt.get_data(as_text=True)
        assert "전체 대상 언어가 함께 포함됩니다" in all_prompt_html
        for label in ("EN:", "JA:", "YUE:"):
            assert label in all_prompt_html
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
