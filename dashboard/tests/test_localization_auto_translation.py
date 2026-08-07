import pytest

from services import localization_auto_translation as auto
from services import localization_management as lms


def _fake_translator(connection, language_code, rows, glossary):
    suffix = " 日本語" if language_code == "ja" else " 廣東話"
    return {
        "translations": [
            {"id": row["id"], "text": row["source_text"].replace("기업", "企業").replace("정보", "情報") + suffix}
            for row in rows
        ]
    }, None


def test_daily_translation_only_fills_pending_target_languages(db_connection, monkeypatch):
    first = lms.register_string(db_connection, "기업정보", page="Header", component="Menu")
    second = lms.register_string(db_connection, "기업 정보", page="Companies")
    lms.save_translation(db_connection, first, "ja", "企業情報")
    db_connection.commit()
    monkeypatch.setattr(auto.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(auto.config, "LOCALIZATION_TRANSLATION_LANGUAGES", "ja,yue-HK")

    result = auto.run_daily(
        db_connection, ".", scan=False, call_openai=_fake_translator
    )

    assert result["languages"]["ja"]["pending"] == 1
    assert result["languages"]["yue-HK"]["pending"] == 2
    assert db_connection.execute(
        "SELECT translated_text FROM localization_translations WHERE string_id=? AND language_code='ja'",
        (first,),
    ).fetchone()[0] == "企業情報"
    assert db_connection.execute(
        "SELECT COUNT(*) FROM localization_translations WHERE status='Completed'"
    ).fetchone()[0] == 4


def test_invalid_or_english_only_responses_are_not_saved(db_connection, monkeypatch):
    first = lms.register_string(db_connection, "기업 {count}건", page="Companies")
    second = lms.register_string(db_connection, "카지노 뉴스", page="News")
    db_connection.commit()
    monkeypatch.setattr(auto.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(auto.config, "LOCALIZATION_TRANSLATION_LANGUAGES", "ja")

    def invalid_translator(connection, language_code, rows, glossary):
        return {"translations": [
            {"id": first, "text": "企業 3件"},
            {"id": second, "text": "Casino News"},
        ]}, None

    result = auto.run_daily(
        db_connection, ".", scan=False, call_openai=invalid_translator
    )

    assert result["languages"]["ja"]["saved"] == 0
    assert result["languages"]["ja"]["rejected"] == 2
    assert db_connection.execute(
        "SELECT COUNT(*) FROM localization_translations"
    ).fetchone()[0] == 0


def test_translation_model_uses_its_own_cost_rates(monkeypatch):
    monkeypatch.setattr(auto.config, "OPENAI_TRANSLATION_MODEL", "translation-model")
    monkeypatch.setattr(auto.config, "OPENAI_TRANSLATION_INPUT_COST_PER_1M", 1.0)
    monkeypatch.setattr(auto.config, "OPENAI_TRANSLATION_OUTPUT_COST_PER_1M", 5.0)

    assert auto.ai_insights._estimate_cost(
        1_000_000, 1_000_000, "translation-model"
    ) == 6.0


def test_number_validation_allows_translated_units_but_not_changed_values():
    assert auto._validation_error("방문객 100명", "訪問客 100人", "ja") is None
    assert auto._validation_error("방문객 100명", "訪問客 101人", "ja") == "number or date mismatch"


def test_validation_accepts_numbers_next_to_translated_unit_characters():
    assert auto._validation_error(
        "예: 복지카드 연 120만원",
        "例：福利カード 年120万ウォン",
        "ja",
    ) is None
    assert auto._validation_error("최근 14일", "最近14日", "ja") is None


def test_translation_prompt_requires_literal_numeric_preservation():
    prompt = auto._system_prompt("ja", [])

    assert "Every digit sequence" in prompt
    assert "Never spell digits out or introduce new digits" in prompt
    assert "must contain zero Hangul characters" in prompt


def test_english_is_supported_and_rejects_untranslated_hangul(monkeypatch):
    monkeypatch.setattr(
        auto.config, "LOCALIZATION_TRANSLATION_LANGUAGES", "en,ja,yue-HK"
    )

    assert auto.configured_languages() == ["en", "ja", "yue-HK"]
    assert auto._validation_error("홈", "Home", "en") is None
    assert auto._validation_error("홈", "홈", "en") == "CJK text remains in English translation"
    assert auto._validation_error("기업", "企業", "en") == "CJK text remains in English translation"


def test_manual_translation_runs_all_pending_rows_in_batches(
    db_connection, monkeypatch
):
    for text in ("기업 정보", "기업정보", "정보 기업"):
        lms.register_string(db_connection, text, page="Manual API")
    db_connection.commit()
    monkeypatch.setattr(auto.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(auto.config, "LOCALIZATION_TRANSLATION_LANGUAGES", "ja,yue-HK")
    monkeypatch.setattr(auto.config, "LOCALIZATION_TRANSLATION_BATCH_SIZE", 2)
    monkeypatch.setattr(
        auto.localization_management, "scan_project",
        lambda connection, root: {"files_scanned": 1, "strings_seen": 3},
    )

    result = auto.run_manual_batch(
        db_connection, ".", "ja", call_openai=_fake_translator
    )

    assert result["pending"] == 3
    assert result["saved"] == 3
    assert result["rejected"] == 0
    assert result["remaining"] == 0
    run = db_connection.execute(
        """SELECT status, prompt_version FROM dashboard_analysis_runs
           WHERE run_type=? ORDER BY id DESC LIMIT 1""",
        (auto.RUN_TYPE,),
    ).fetchone()
    assert (run["status"], run["prompt_version"]) == ("success", "manual:ja")


def test_manual_and_scheduled_translation_share_a_run_lock(db_connection, monkeypatch):
    monkeypatch.setattr(auto.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(auto.config, "LOCALIZATION_TRANSLATION_LANGUAGES", "ja")
    db_connection.execute(
        """INSERT INTO dashboard_analysis_runs
           (run_type, started_at, status, prompt_version)
           VALUES (?, ?, 'running', 'scheduled')""",
        (auto.RUN_TYPE, auto.now_kst().isoformat()),
    )
    db_connection.commit()

    with pytest.raises(auto.TranslationRunInProgress, match="이미 API 번역 작업"):
        auto.run_manual_batch(
            db_connection, ".", "ja", call_openai=_fake_translator
        )


def test_admin_api_translation_route_enforces_role_csrf_and_reports_result(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "manual-translation-route.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    import app as app_module
    from dashboard_db import schema

    connection = schema.connect(str(db_path))
    admin_id = connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,is_active,created_at)
           VALUES ('api-admin','unused','admin',1,'2026-08-04T00:00:00')"""
    ).lastrowid
    user_id = connection.execute(
        """INSERT INTO dashboard_users
           (username,password_hash,role,is_active,created_at)
           VALUES ('api-user','unused','user',1,'2026-08-04T00:00:00')"""
    ).lastrowid
    connection.commit()
    connection.close()
    monkeypatch.setattr(
        auto, "run_manual_batch",
        lambda connection, root, language_code, actor_id=None: {
            "language_code": language_code, "pending": 12, "saved": 10,
            "rejected": 2, "remaining": 31, "error": None,
        },
    )

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        assert client.post("/admin/localization/api-translate").status_code == 302
        with client.session_transaction() as browser_session:
            browser_session.update(
                user_id=user_id, username="api-user", role="user",
                csrf_token="u" * 64,
            )
        assert client.post(
            "/admin/localization/api-translate",
            data={"csrf_token": "u" * 64, "language_code": "ja"},
        ).status_code == 403
        with client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session.update(
                user_id=admin_id, username="api-admin", role="admin",
                csrf_token="a" * 64,
            )
        page = client.get("/admin/localization?language=ja")
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert "API 번역 시작하기" in html
        assert 'action="/admin/localization/api-translate"' in html
        assert client.post(
            "/admin/localization/api-translate",
            data={"csrf_token": "wrong", "language_code": "ja"},
        ).status_code == 400
        response = client.post(
            "/admin/localization/api-translate",
            data={"csrf_token": "a" * 64, "language_code": "ja"},
            follow_redirects=True,
        )
        result_html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "API 번역 완료" in result_html
        assert "저장 10건" in result_html
        assert "남은 항목 31건" in result_html
