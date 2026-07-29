"""
대시보드 자체 DB(dashboard.db) 연결 및 스키마 마이그레이션.

기존 casino_news_watch/database.py, email_monitor/database.py와 동일한 패턴을
따른다: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN(멱등)으로 안전하게
반복 실행 가능한 마이그레이션. 뉴스/이메일 프로그램의 DB는 이 모듈에서 전혀
다루지 않는다(읽기 전용 접근은 services/news_reader.py 참고).
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
    # 기존 계정은 이 기능 도입 전부터 대시보드를 관리하던 계정이므로 admin으로 이관한다.
    _ensure_column(connection, "dashboard_users", "role", "TEXT NOT NULL DEFAULT 'admin'")
    _ensure_column(connection, "dashboard_users", "is_active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "dashboard_users", "updated_at", "TEXT")
    _ensure_column(connection, "dashboard_users", "password_changed_at", "TEXT")
    _ensure_column(connection, "dashboard_users", "landing_page", "TEXT NOT NULL DEFAULT 'dashboard'")
    _ensure_column(connection, "dashboard_users", "email", "TEXT")
    _ensure_column(
        connection, "dashboard_users", "approval_status",
        "TEXT NOT NULL DEFAULT 'approved'",
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dashboard_users_email_unique
        ON dashboard_users(LOWER(email))
        WHERE email IS NOT NULL AND TRIM(email) != ''
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_user_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_user_id INTEGER,
            target_username TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_audit_created "
        "ON dashboard_user_audit(created_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_user_permissions (
            user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
            permission_code TEXT NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            updated_by INTEGER,
            PRIMARY KEY (user_id, permission_code)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS login_ip_security (
            ip_address TEXT PRIMARY KEY,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            first_failed_at TEXT,
            last_failed_at TEXT,
            blocked_at TEXT,
            blocked_by TEXT,
            unblocked_at TEXT,
            note TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS security_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            success INTEGER NOT NULL DEFAULT 1,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_audit_created "
        "ON security_audit_log(created_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_active_sessions (
            session_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
            username TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            absolute_expires_at TEXT NOT NULL,
            revoked_at TEXT,
            revoke_reason TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_sessions_user "
        "ON dashboard_active_sessions(user_id, revoked_at, last_seen_at DESC)"
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
    _ensure_column(connection, "action_items", "reported_by", "TEXT")
    _ensure_column(connection, "action_items", "bug_page", "TEXT")
    _ensure_column(connection, "action_items", "environment", "TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS action_item_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_item_id INTEGER NOT NULL REFERENCES action_items(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            content TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_item_comments_item "
        "ON action_item_comments(action_item_id, is_deleted, created_at)"
    )

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

    # ---- tourism_visitor_stats (출입국관광통계 API 캐시) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tourism_visitor_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ym TEXT NOT NULL,
            nat_label TEXT NOT NULL,
            visitor_count INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(ym, nat_label)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tourism_visitor_stats_ym "
        "ON tourism_visitor_stats(ym)"
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

    # ---- company_research_profiles (공식 자료 기반 기초 조사 베이스라인) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_research_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL UNIQUE,
            dart_corp_code TEXT,
            stock_code TEXT,
            legal_name TEXT,
            legal_name_eng TEXT,
            ceo_names TEXT,
            headquarters TEXT,
            established_date TEXT,
            fiscal_month TEXT,
            website_url TEXT,
            ir_url TEXT,
            business_summary TEXT,
            strategy_summary TEXT,
            key_assets_json TEXT,
            opportunities_json TEXT,
            risks_json TEXT,
            financials_json TEXT,
            sources_json TEXT,
            source_period TEXT,
            researched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_research_code "
        "ON company_research_profiles(dart_corp_code)"
    )

    # ---- research_documents (사용자 업로드 증권사·산업 리포트 자료실) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            title TEXT NOT NULL,
            publisher TEXT,
            report_date TEXT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL UNIQUE,
            mime_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            page_count INTEGER,
            extracted_text TEXT,
            extraction_status TEXT NOT NULL DEFAULT 'pending',
            ai_summary TEXT,
            investment_stance TEXT,
            target_price TEXT,
            key_points_json TEXT,
            risks_json TEXT,
            analyzed_at TEXT,
            error_message TEXT,
            uploaded_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(company_name, sha256)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_documents_company "
        "ON research_documents(company_name, report_date, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_document_companies (
            document_id INTEGER NOT NULL
                REFERENCES research_documents(id) ON DELETE CASCADE,
            company_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (document_id, company_name)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_document_companies_company "
        "ON research_document_companies(company_name, document_id)"
    )
    # 기존 단일 회사 자료도 새 다중 연결 구조에서 그대로 검색되도록 이관한다.
    connection.execute(
        """
        INSERT OR IGNORE INTO research_document_companies
            (document_id, company_name, created_at)
        SELECT id, company_name, created_at
        FROM research_documents
        WHERE company_name IS NOT NULL AND TRIM(company_name) != ''
        """
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
        CREATE TABLE IF NOT EXISTS legislative_bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id TEXT NOT NULL UNIQUE,
            bill_no TEXT,
            era TEXT,
            bill_kind TEXT,
            bill_name TEXT NOT NULL,
            proposer_kind TEXT,
            proposer_name TEXT,
            proposed_date TEXT,
            committee_name TEXT,
            committee_result TEXT,
            plenary_result TEXT,
            process_stage TEXT,
            pass_status TEXT,
            link_url TEXT,
            pdf_url TEXT,
            matched_keyword TEXT,
            ai_summary TEXT,
            impact_direction TEXT,
            impact_level TEXT,
            impact_reason TEXT,
            action_needed TEXT,
            analysis_source TEXT,
            analyzed_at TEXT,
            analysis_error TEXT,
            first_seen_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_legislative_bills_proposed "
        "ON legislative_bills(proposed_date DESC)"
    )
    _ensure_column(connection, "legislative_bills", "ai_summary", "TEXT")
    _ensure_column(connection, "legislative_bills", "impact_direction", "TEXT")
    _ensure_column(connection, "legislative_bills", "impact_level", "TEXT")
    _ensure_column(connection, "legislative_bills", "impact_reason", "TEXT")
    _ensure_column(connection, "legislative_bills", "action_needed", "TEXT")
    _ensure_column(connection, "legislative_bills", "analysis_source", "TEXT")
    _ensure_column(connection, "legislative_bills", "analyzed_at", "TEXT")
    _ensure_column(connection, "legislative_bills", "analysis_error", "TEXT")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_quotes (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            market TEXT,
            base_date TEXT,
            close_price REAL,
            change_value REAL,
            change_rate REAL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            volume INTEGER,
            market_cap INTEGER,
            fetched_at TEXT NOT NULL
        )
        """
    )
    _ensure_column(connection, "market_quotes", "market_cap", "INTEGER")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_quote_history (
            symbol TEXT NOT NULL,
            base_date TEXT NOT NULL,
            close_price REAL NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (symbol, base_date)
        )
        """
    )

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

    # ---- 공문·자료관리 기준정보 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_doc_reference_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            code TEXT NOT NULL,
            label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(kind, code)
        )
        """
    )

    # ---- 공문·자료관리 문서 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            management_number TEXT NOT NULL UNIQUE,
            receipt_number TEXT,
            manager TEXT NOT NULL,
            receipt_date TEXT NOT NULL,
            organization TEXT NOT NULL,
            case_name TEXT,
            request_content TEXT NOT NULL,
            special_note TEXT,
            requester TEXT,
            contact TEXT,
            email TEXT,
            dispatch_number TEXT,
            reply_date TEXT,
            location TEXT,
            legacy_location TEXT,
            video_exported TEXT NOT NULL DEFAULT '해당없음',
            export_pledge TEXT NOT NULL DEFAULT '해당없음',
            category_code TEXT NOT NULL,
            category_detail TEXT,
            folder_category_code TEXT NOT NULL,
            folder_category_detail TEXT,
            processing_result TEXT NOT NULL DEFAULT '처리 필요',
            registered_by TEXT NOT NULL,
            registered_user_id INTEGER REFERENCES dashboard_users(id),
            registered_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            temp_file_status TEXT NOT NULL DEFAULT 'UPLOADED',
            storage_status TEXT NOT NULL DEFAULT 'UPLOADED',
            sha256_hash TEXT,
            verified_at TEXT,
            error_message TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            duplicate_warning_ack INTEGER NOT NULL DEFAULT 0,
            claim_client TEXT,
            claimed_at TEXT,
            claim_expires_at TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_documents_dates "
        "ON official_documents(receipt_date, registered_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_documents_status "
        "ON official_documents(storage_status, processing_result, is_active)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_receipt_counters (
            year TEXT NOT NULL,
            manager TEXT NOT NULL,
            last_sequence INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (year, manager)
        )
        """
    )
    for column, definition in (
        ("folder_handling_type", "TEXT NOT NULL DEFAULT 'CREATE_NEW'"),
        ("requested_folder_path", "TEXT"),
        ("normalized_unc_path", "TEXT"),
        ("folder_display_name", "TEXT"),
        ("folder_link_status", "TEXT"),
        ("folder_link_note", "TEXT"),
        ("folder_verified_at", "TEXT"),
        ("folder_verified_by_client", "TEXT"),
        ("excel_exported_at", "TEXT"),
        ("deleted_at", "TEXT"),
        ("delete_after", "TEXT"),
        ("deleted_by", "TEXT"),
        ("file_delete_status", "TEXT"),
        ("file_deleted_at", "TEXT"),
        ("file_delete_client", "TEXT"),
        ("file_delete_error", "TEXT"),
    ):
        _ensure_column(connection, "official_documents", column, definition)
    connection.execute(
        """
        UPDATE official_documents SET file_delete_status='PENDING'
        WHERE is_active=0 AND delete_after IS NOT NULL AND file_delete_status IS NULL
        """
    )

    # ---- 공문·자료관리 다중 PDF 첨부 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_document_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES official_documents(id),
            attachment_type TEXT NOT NULL DEFAULT '일반자료',
            original_filename TEXT NOT NULL,
            temp_filename TEXT,
            final_filename TEXT,
            file_size INTEGER NOT NULL,
            mime_type TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            temp_status TEXT NOT NULL DEFAULT 'UPLOADED',
            final_path TEXT,
            registered_at TEXT NOT NULL,
            stored_at TEXT,
            temp_deleted_at TEXT,
            UNIQUE(document_id, sha256)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_attachments_document "
        "ON official_document_attachments(document_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_attachments_hash "
        "ON official_document_attachments(sha256)"
    )

    # ---- 공문·자료관리 처리이력 ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_document_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER REFERENCES official_documents(id),
            attachment_id INTEGER REFERENCES official_document_attachments(id),
            action TEXT NOT NULL,
            actor TEXT,
            client_name TEXT,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_history_document "
        "ON official_document_history(document_id, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_document_change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_history_id INTEGER UNIQUE,
            document_id INTEGER,
            management_number TEXT,
            attachment_id INTEGER,
            action TEXT NOT NULL,
            actor TEXT,
            client_name TEXT,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_change_log_created "
        "ON official_document_change_log(created_at DESC)"
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO official_document_change_log
            (source_history_id, document_id, management_number, attachment_id,
             action, actor, client_name, detail_json, created_at)
        SELECT h.id, h.document_id, d.management_number, h.attachment_id,
               h.action, h.actor, h.client_name, h.detail_json, h.created_at
        FROM official_document_history h
        LEFT JOIN official_documents d ON d.id=h.document_id
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_folder_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            unc_path TEXT NOT NULL UNIQUE,
            year INTEGER,
            folder_category TEXT,
            file_count INTEGER NOT NULL DEFAULT 0,
            last_modified_at TEXT,
            last_scanned_at TEXT NOT NULL,
            is_available INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_official_folder_search "
        "ON official_folder_index(year, folder_category, is_available)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS official_excel_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            export_type TEXT NOT NULL,
            exported_by TEXT NOT NULL,
            exported_user_id INTEGER REFERENCES dashboard_users(id),
            exported_at TEXT NOT NULL,
            filter_conditions TEXT,
            record_count INTEGER NOT NULL,
            output_filename TEXT NOT NULL,
            includes_personal_data INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # ---- tips board (migrated from the portfolio JSON board) ----
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_articles (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '기타',
            tags_json TEXT NOT NULL DEFAULT '[]',
            published_date TEXT NOT NULL,
            updated_date TEXT NOT NULL,
            reading_time TEXT,
            featured INTEGER NOT NULL DEFAULT 0,
            draft INTEGER NOT NULL DEFAULT 0,
            cover_image TEXT,
            author_id INTEGER REFERENCES dashboard_users(id),
            view_count INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_public_order "
        "ON tips_articles(is_deleted, draft, featured DESC, published_date DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_category "
        "ON tips_articles(category, is_deleted, draft)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_id TEXT NOT NULL REFERENCES tips_articles(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            content TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            deleted_by INTEGER REFERENCES dashboard_users(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_comments_tip "
        "ON tips_comments(tip_id, is_deleted, created_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_id TEXT NOT NULL REFERENCES tips_articles(id) ON DELETE CASCADE,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL UNIQUE,
            mime_type TEXT,
            file_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            uploaded_by INTEGER REFERENCES dashboard_users(id),
            created_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tips_attachments_tip "
        "ON tips_attachments(tip_id, is_deleted, created_at)"
    )

    defaults = {
        "category": [
            ("01-1", "01-1. 공문접수"), ("01-2", "01-2. 공문발송"),
            ("02", "02. 문서접수(공문 外)"), ("03", "03. 수사협조요청"),
            ("04", "04. 영상반출확약서"), ("OTHER", "기타"),
        ],
        "folder_category": [
            ("071", "071. 본사"), ("072", "072. 수사기관"), ("073", "073. 문체부"),
            ("074", "074. 카지노협회"), ("075", "075. 국회"),
            ("076", "076. 사행성감독위원회"), ("077", "077. 고객"),
            ("078", "078. 기타"), ("079", "079. 직원"),
        ],
    }
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    for kind, values in defaults.items():
        for order, (code, label) in enumerate(values, 1):
            connection.execute(
                """
                INSERT OR IGNORE INTO official_doc_reference_values
                    (kind, code, label, active, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (kind, code, label, order, now_iso, now_iso),
            )

    connection.commit()
