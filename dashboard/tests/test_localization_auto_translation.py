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
