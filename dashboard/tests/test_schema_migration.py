from dashboard_db import queries, schema
import extensions

EXPECTED_TABLES = {
    "dashboard_users", "action_items", "action_item_comments", "executive_insights", "performance_reports",
    "tourism_visitor_stats",
    "dashboard_analysis_runs", "telegram_ingest_state", "monitored_companies",
    "company_research_profiles", "research_documents",
    "dart_disclosures", "disclosure_analysis", "monitored_laws", "law_updates",
    "law_analysis", "legislative_bills", "government_legislative_notices",
    "market_quotes", "market_quote_history", "economic_series",
    "source_data_series", "source_data_points", "source_data_repository_state",
    "api_usage", "errors",
}


def test_migrate_creates_all_expected_tables(db_connection):
    rows = db_connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row["name"] for row in rows}
    assert EXPECTED_TABLES.issubset(table_names)


def test_dashboard_users_support_persistent_home_hero_preference(db_connection):
    columns = {
        row["name"]: row
        for row in db_connection.execute("PRAGMA table_info(dashboard_users)")
    }
    assert "hero_preference" in columns
    assert columns["hero_preference"]["notnull"] == 0


def test_migrate_is_idempotent(tmp_path):
    db_path = tmp_path / "idempotent.db"
    conn1 = schema.connect(str(db_path))
    conn1.execute(
        "INSERT INTO dashboard_users (username, password_hash, created_at) VALUES (?, ?, ?)",
        ("someone", "hash", "2026-01-01T00:00:00+09:00"),
    )
    conn1.commit()
    conn1.close()

    # 두 번째 연결(재실행)에서도 기존 데이터가 그대로 보존되어야 한다.
    conn2 = schema.connect(str(db_path))
    row = conn2.execute("SELECT username FROM dashboard_users WHERE username = ?", ("someone",)).fetchone()
    assert row is not None
    conn2.close()


def test_current_schema_uses_sqlite_version_marker(tmp_path, monkeypatch):
    db_path = tmp_path / "versioned.db"
    connection = schema.connect(str(db_path))
    assert schema.is_current(connection)
    connection.close()

    calls = []
    monkeypatch.setattr(
        schema,
        "migrate",
        lambda connection: calls.append(1),
    )
    connection = schema.connect(str(db_path))
    connection.close()
    assert calls == []


def test_research_documents_have_non_destructive_document_type_default(db_connection):
    columns = {
        row["name"]: row
        for row in db_connection.execute("PRAGMA table_info(research_documents)")
    }
    assert columns["document_type"]["notnull"] == 1
    assert columns["document_type"]["dflt_value"] == "'research'"


def test_web_database_helper_migrates_once_per_database_file(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime.db"
    monkeypatch.setattr(extensions.config, "DASHBOARD_DB_FILE", str(db_path))
    original_migrate = schema.migrate
    calls = []

    def counted_migrate(connection):
        calls.append(1)
        return original_migrate(connection)

    monkeypatch.setattr(schema, "migrate", counted_migrate)
    extensions._migrated_database_identities.clear()
    try:
        first = extensions.dashboard_db()
        second = extensions.dashboard_db()
        assert first.execute("SELECT 1").fetchone()[0] == 1
        assert second.execute("SELECT 1").fetchone()[0] == 1
        assert len(calls) == 1
        first.close()
        second.close()
    finally:
        extensions._migrated_database_identities.clear()


def test_latest_disclosure_analyses_are_loaded_in_one_batch(db_connection):
    disclosure_ids = []
    for index in range(2):
        cursor = db_connection.execute(
            """
            INSERT INTO dart_disclosures
                (rcept_no, corp_name, report_nm, rcept_dt, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"receipt-{index}", "테스트기업", "사업보고서", "20260803", "2026-08-03"),
        )
        disclosure_ids.append(cursor.lastrowid)
    for summary in ("이전 분석", "최신 분석"):
        db_connection.execute(
            """
            INSERT INTO disclosure_analysis
                (disclosure_id, ai_summary, analyzed_at)
            VALUES (?, ?, ?)
            """,
            (disclosure_ids[0], summary, "2026-08-03"),
        )
    db_connection.execute(
        """
        INSERT INTO disclosure_analysis (disclosure_id, ai_summary, analyzed_at)
        VALUES (?, ?, ?)
        """,
        (disclosure_ids[1], "두 번째 기업 분석", "2026-08-03"),
    )
    db_connection.commit()

    analyses = queries.list_latest_disclosure_analyses(
        db_connection, disclosure_ids
    )
    assert analyses[disclosure_ids[0]]["ai_summary"] == "최신 분석"
    assert analyses[disclosure_ids[1]]["ai_summary"] == "두 번째 기업 분석"
