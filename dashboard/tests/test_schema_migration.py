from dashboard_db import schema

EXPECTED_TABLES = {
    "dashboard_users", "action_items", "action_item_comments", "executive_insights", "performance_reports",
    "tourism_visitor_stats",
    "dashboard_analysis_runs", "telegram_ingest_state", "monitored_companies",
    "company_research_profiles", "research_documents",
    "dart_disclosures", "disclosure_analysis", "monitored_laws", "law_updates",
    "law_analysis", "legislative_bills", "government_legislative_notices",
    "market_quotes", "market_quote_history", "economic_series",
    "api_usage", "errors",
}


def test_migrate_creates_all_expected_tables(db_connection):
    rows = db_connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row["name"] for row in rows}
    assert EXPECTED_TABLES.issubset(table_names)


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
