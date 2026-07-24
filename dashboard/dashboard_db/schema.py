"""
대시보드 자체 DB(dashboard.db) 연결 및 스키마 마이그레이션.

기존 casino_news_watch/database.py, email_monitor/database.py와 동일한 패턴을
따른다: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN(멱등)으로 안전하게
반복 실행 가능한 마이그레이션. 뉴스/이메일 프로그램의 DB는 이 모듈에서 전혀
다루지 않는다(읽기 전용 접근은 services/news_reader.py, services/email_reader.py 참고).
"""

import sqlite3

import config


def connect(db_path=None):
    """대시보드 DB에 연결하고 마이그레이션을 실행한다."""
    connection = sqlite3.connect(db_path or config.DASHBOARD_DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate(connection)
    return connection


def _ensure_column(connection, table, column, coltype):
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def migrate(connection):
    """스키마를 최신 상태로 맞춘다. 기존 테이블/데이터는 절대 삭제하지 않는다."""

    # ---- dashboard_users ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )
        """
    )

    # ---- action_items ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            source_type TEXT NOT NULL DEFAULT 'manual',
            source_ref_id TEXT,
            owner TEXT,
            created_at TEXT NOT NULL,
            due_date TEXT,
            due_date_confidence TEXT DEFAULT 'unclear',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'not_started',
            ai_suggested INTEGER NOT NULL DEFAULT 0,
            approved_by_user INTEGER NOT NULL DEFAULT 1,
            ai_recommended_action TEXT,
            completed_at TEXT,
            memo TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_action_items_status ON action_items(status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_action_items_due_date ON action_items(due_date)")

    # ---- executive_insights ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS executive_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_date TEXT NOT NULL,
            title TEXT NOT NULL,
            importance TEXT NOT NULL DEFAULT 'medium',
            evidence_json TEXT,
            facts TEXT,
            ai_interpretation TEXT,
            expected_impact TEXT,
            recommended_action TEXT,
            needs_executive_review INTEGER NOT NULL DEFAULT 0,
            category TEXT NOT NULL DEFAULT 'estimate',
            prompt_version TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_executive_insights_date ON executive_insights(insight_date)"
    )

    # ---- performance_reports (텔레그램 실적 메시지 수집) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS performance_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            telegram_update_id INTEGER,
            telegram_message_id INTEGER,
            telegram_chat_id TEXT,
            message_kind TEXT NOT NULL,
            header_type TEXT,
            raw_text TEXT,
            parsed_json TEXT,
            parsing_status TEXT NOT NULL DEFAULT 'ok',
            parsing_error TEXT,
            received_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_perf_reports_message "
        "ON performance_reports(telegram_chat_id, telegram_message_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_perf_reports_date ON performance_reports(report_date)"
    )

    # ---- dashboard_analysis_runs ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            prompt_version TEXT,
            input_hash TEXT,
            error_message TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_runs_type ON dashboard_analysis_runs(run_type, started_at)"
    )

    # ---- telegram_ingest_state (getUpdates 오프셋, 단일 행) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_ingest_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_update_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )

    # ---- monitored_companies (DART 관심기업) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS monitored_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            dart_corp_code TEXT,
            aliases_json TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_monitored_companies_code "
        "ON monitored_companies(dart_corp_code)"
    )

    # ---- dart_disclosures ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dart_disclosures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rcept_no TEXT NOT NULL UNIQUE,
            corp_name TEXT,
            dart_corp_code TEXT,
            report_nm TEXT,
            pblntf_ty TEXT,
            rcept_dt TEXT,
            flr_nm TEXT,
            dart_link TEXT,
            is_important INTEGER NOT NULL DEFAULT 0,
            telegram_alert_sent_at TEXT,
            fetched_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_dart_disclosures_dt ON dart_disclosures(rcept_dt)")

    # ---- disclosure_analysis ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS disclosure_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disclosure_id INTEGER NOT NULL REFERENCES dart_disclosures(id),
            ai_summary TEXT,
            importance TEXT,
            financial_impact TEXT,
            competitive_impact TEXT,
            risk_category TEXT,
            needs_executive_review INTEGER NOT NULL DEFAULT 0,
            prompt_version TEXT,
            analyzed_at TEXT,
            error_message TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_disclosure_analysis_disclosure "
        "ON disclosure_analysis(disclosure_id)"
    )

    # ---- monitored_laws ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS monitored_laws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            law_name TEXT NOT NULL UNIQUE,
            law_id TEXT,
            mst TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # ---- law_updates ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS law_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitored_law_id INTEGER NOT NULL REFERENCES monitored_laws(id),
            snapshot_hash TEXT NOT NULL,
            effective_date TEXT,
            promulgation_date TEXT,
            status TEXT,
            raw_summary_json TEXT,
            fetched_at TEXT NOT NULL,
            is_new INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_law_updates_law ON law_updates(monitored_law_id, fetched_at)"
    )

    # ---- law_analysis ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS law_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            law_update_id INTEGER NOT NULL REFERENCES law_updates(id),
            ai_summary TEXT,
            affected_scope TEXT,
            company_impact TEXT,
            action_needed TEXT,
            prompt_version TEXT,
            analyzed_at TEXT,
            error_message TEXT
        )
        """
    )

    # ---- api_usage (대시보드 자체 OpenAI 호출 비용/호출량 보호용) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            called_at TEXT NOT NULL,
            model TEXT,
            request_type TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            estimated_cost REAL,
            success INTEGER NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_called_at ON api_usage(called_at)")

    # ---- errors (전 구간 공통 오류 로그) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            stage TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            notified INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_errors_occurred_at ON errors(occurred_at)")

    connection.commit()
