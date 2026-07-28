"""
dashboard.db에 대한 CRUD 함수 모음.

기존 database.py들과 동일하게 sqlite3.Row 기반 함수형 스타일을 따른다.
AI가 생성한 내용(ai_suggested=1 등)과 사용자가 직접 입력/승인한 내용을
필드로 명확히 구분한다.
"""

import json

from utils import now_kst

# ============================================================
# dashboard_users
# ============================================================

def get_user_by_username(connection, username):
    row = connection.execute(
        "SELECT * FROM dashboard_users WHERE username = ?", (username,)
    ).fetchone()
    return dict(row) if row else None


def create_user(connection, username, password_hash, role="user"):
    now_iso = now_kst().isoformat()
    cursor = connection.execute(
        "INSERT INTO dashboard_users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
        (username, password_hash, role, now_iso),
    )
    connection.commit()
    return cursor.lastrowid


def touch_last_login(connection, user_id):
    connection.execute(
        "UPDATE dashboard_users SET last_login_at = ? WHERE id = ?",
        (now_kst().isoformat(), user_id),
    )
    connection.commit()


def any_user_exists(connection):
    row = connection.execute("SELECT 1 FROM dashboard_users LIMIT 1").fetchone()
    return row is not None


def get_user_permissions(connection, user_id, permission_codes):
    rows = connection.execute(
        "SELECT permission_code, allowed FROM dashboard_user_permissions WHERE user_id=?",
        (user_id,),
    ).fetchall()
    saved = {row["permission_code"]: bool(row["allowed"]) for row in rows}
    # Existing accounts keep their current access until an administrator saves
    # an explicit permission matrix for them.
    return {code: saved.get(code, True) for code in permission_codes}


def replace_user_permissions(connection, user_id, permission_codes, allowed_codes, updated_by):
    now_iso = now_kst().isoformat()
    connection.execute(
        "DELETE FROM dashboard_user_permissions WHERE user_id=?", (user_id,)
    )
    connection.executemany(
        """
        INSERT INTO dashboard_user_permissions
            (user_id, permission_code, allowed, updated_at, updated_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (user_id, code, 1 if code in allowed_codes else 0, now_iso, updated_by)
            for code in permission_codes
        ],
    )
    connection.commit()


# ============================================================
# action_items
# ============================================================

def create_action_item(
    connection,
    title,
    description="",
    source_type="manual",
    source_ref_id=None,
    owner=None,
    due_date=None,
    due_date_confidence="unclear",
    priority="normal",
    ai_suggested=False,
    ai_recommended_action=None,
    status="not_started",
    reported_by=None,
    bug_page=None,
    environment=None,
):
    now_iso = now_kst().isoformat()
    cursor = connection.execute(
        """
        INSERT INTO action_items (
            title, description, source_type, source_ref_id, owner, created_at,
            due_date, due_date_confidence, priority, status, ai_suggested,
            approved_by_user, ai_recommended_action, updated_at, reported_by,
            bug_page, environment
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title, description, source_type, source_ref_id, owner, now_iso,
            due_date, due_date_confidence, priority, status,
            1 if ai_suggested else 0,
            0 if ai_suggested else 1,  # AI 제안은 기본 미승인 상태로 저장
            ai_recommended_action, now_iso, reported_by, bug_page, environment,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def list_action_items(connection, status=None, only_pending_due=False, reported_by=None):
    query = "SELECT * FROM action_items"
    params = []
    clauses = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if reported_by is not None:
        clauses.append("reported_by = ?")
        params.append(reported_by)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY CASE priority WHEN '긴급' THEN 0 WHEN 'urgent' THEN 0 ELSE 1 END, due_date IS NULL, due_date ASC"
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_action_item(connection, item_id):
    row = connection.execute("SELECT * FROM action_items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def update_action_item(connection, item_id, **fields):
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = now_kst().isoformat()
    if fields.get("status") == "완료" or fields.get("status") == "done":
        fields.setdefault("completed_at", now_kst().isoformat())
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [item_id]
    connection.execute(f"UPDATE action_items SET {columns} WHERE id = ?", values)
    connection.commit()


def approve_action_item(connection, item_id):
    connection.execute(
        "UPDATE action_items SET approved_by_user = 1, updated_at = ? WHERE id = ?",
        (now_kst().isoformat(), item_id),
    )
    connection.commit()


def delete_action_item(connection, item_id):
    connection.execute("DELETE FROM action_items WHERE id = ?", (item_id,))
    connection.commit()


def count_action_items(
    connection, status=None, overdue_only=False, due_today_only=False,
    urgent_only=False, reported_by=None,
):
    today = now_kst().strftime("%Y-%m-%d")
    query = (
        "SELECT COUNT(*) AS c FROM action_items "
        "WHERE status NOT IN ('완료', 'done', '해결', '종료')"
    )
    params = []
    if status:
        query = "SELECT COUNT(*) AS c FROM action_items WHERE status = ?"
        params = [status]
    elif overdue_only:
        query += " AND due_date IS NOT NULL AND due_date < ?"
        params.append(today)
    elif due_today_only:
        query += " AND due_date = ?"
        params.append(today)
    elif urgent_only:
        query += " AND priority IN ('긴급', 'urgent')"
    if reported_by is not None:
        query += " AND reported_by = ?"
        params.append(reported_by)
    row = connection.execute(query, params).fetchone()
    return row["c"] if row else 0


# ============================================================
# executive_insights
# ============================================================

def create_executive_insight(
    connection,
    insight_date,
    title,
    importance,
    evidence,
    facts,
    ai_interpretation,
    expected_impact,
    recommended_action,
    needs_executive_review,
    category,
    prompt_version,
):
    connection.execute(
        """
        INSERT INTO executive_insights (
            insight_date, title, importance, evidence_json, facts, ai_interpretation,
            expected_impact, recommended_action, needs_executive_review, category,
            prompt_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            insight_date, title, importance, json.dumps(evidence, ensure_ascii=False),
            facts, ai_interpretation, expected_impact, recommended_action,
            1 if needs_executive_review else 0, category, prompt_version,
            now_kst().isoformat(),
        ),
    )
    connection.commit()


def list_insights_for_date(connection, insight_date):
    rows = connection.execute(
        "SELECT * FROM executive_insights WHERE insight_date = ? ORDER BY "
        "CASE importance WHEN 'high' THEN 0 WHEN '높음' THEN 0 ELSE 1 END, id DESC",
        (insight_date,),
    ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        try:
            item["evidence"] = json.loads(item.get("evidence_json") or "[]")
        except (ValueError, TypeError):
            item["evidence"] = []
        results.append(item)
    return results


def count_insights_for_date(connection, insight_date):
    row = connection.execute(
        "SELECT COUNT(*) AS c FROM executive_insights WHERE insight_date = ?",
        (insight_date,),
    ).fetchone()
    return row["c"] if row else 0


# ============================================================
# performance_reports
# ============================================================

def save_performance_report(
    connection,
    report_date,
    telegram_update_id,
    telegram_message_id,
    telegram_chat_id,
    message_kind,
    header_type,
    raw_text,
    parsed_data,
    parsing_status,
    parsing_error,
    received_at,
):
    """중복(같은 chat_id+message_id)이면 조용히 무시한다(스펙: 동일 메시지 중복 저장 방지)."""
    connection.execute(
        """
        INSERT OR IGNORE INTO performance_reports (
            report_date, telegram_update_id, telegram_message_id, telegram_chat_id,
            message_kind, header_type, raw_text, parsed_json, parsing_status,
            parsing_error, received_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_date, telegram_update_id, telegram_message_id, telegram_chat_id,
            message_kind, header_type, raw_text,
            json.dumps(parsed_data, ensure_ascii=False) if parsed_data is not None else None,
            parsing_status, parsing_error, received_at, now_kst().isoformat(),
        ),
    )
    connection.commit()


def list_performance_reports(connection, report_date, only_parsed=False):
    query = "SELECT * FROM performance_reports WHERE report_date = ?"
    if only_parsed:
        query += " AND parsing_status = 'ok'"
    query += " ORDER BY received_at DESC"
    rows = connection.execute(query, (report_date,)).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        try:
            item["parsed"] = json.loads(item["parsed_json"]) if item["parsed_json"] else None
        except (ValueError, TypeError):
            item["parsed"] = None
        results.append(item)
    return results


def get_latest_performance_report(connection, report_date=None):
    if report_date:
        row = connection.execute(
            "SELECT * FROM performance_reports WHERE report_date = ? AND parsing_status = 'ok' "
            "ORDER BY received_at DESC LIMIT 1",
            (report_date,),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT * FROM performance_reports WHERE parsing_status = 'ok' "
            "ORDER BY received_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["parsed"] = json.loads(item["parsed_json"]) if item["parsed_json"] else None
    except (ValueError, TypeError):
        item["parsed"] = None
    return item


# ============================================================
# telegram_ingest_state
# ============================================================

def get_last_update_id(connection):
    row = connection.execute(
        "SELECT last_update_id FROM telegram_ingest_state WHERE id = 1"
    ).fetchone()
    return row["last_update_id"] if row else 0


def set_last_update_id(connection, update_id):
    connection.execute(
        """
        INSERT INTO telegram_ingest_state (id, last_update_id, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET last_update_id = excluded.last_update_id,
                                       updated_at = excluded.updated_at
        """,
        (update_id, now_kst().isoformat()),
    )
    connection.commit()


# ============================================================
# monitored_companies (DART)
# ============================================================

def list_monitored_companies(connection, active_only=True):
    query = "SELECT * FROM monitored_companies"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name"
    return [dict(row) for row in connection.execute(query).fetchall()]


def upsert_monitored_company(connection, name, dart_corp_code, aliases=None, active=True):
    connection.execute(
        """
        INSERT INTO monitored_companies (name, dart_corp_code, aliases_json, active, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(dart_corp_code) DO UPDATE SET
            name = excluded.name, aliases_json = excluded.aliases_json, active = excluded.active
        """,
        (
            name, dart_corp_code,
            json.dumps(aliases or [], ensure_ascii=False),
            1 if active else 0,
            now_kst().isoformat(),
        ),
    )
    connection.commit()


def upsert_company_research(connection, company_name, **fields):
    allowed = {
        "dart_corp_code", "stock_code", "legal_name", "legal_name_eng", "ceo_names",
        "headquarters", "established_date", "fiscal_month", "website_url", "ir_url",
        "business_summary", "strategy_summary", "key_assets_json", "opportunities_json",
        "risks_json", "financials_json", "sources_json", "source_period",
        "researched_at", "updated_at",
    }
    values = {key: value for key, value in fields.items() if key in allowed}
    now_iso = now_kst().isoformat()
    values.setdefault("researched_at", now_iso)
    values.setdefault("updated_at", now_iso)
    columns = ["company_name", *values]
    params = [company_name, *values.values()]
    updates = ", ".join(f"{column}=excluded.{column}" for column in values)
    connection.execute(
        f"INSERT INTO company_research_profiles ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT(company_name) DO UPDATE SET {updates}",
        params,
    )
    connection.commit()


def list_company_research(connection):
    rows = connection.execute(
        "SELECT * FROM company_research_profiles ORDER BY company_name"
    ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        for field in ("key_assets_json", "opportunities_json", "risks_json",
                      "financials_json", "sources_json"):
            target = field.removesuffix("_json")
            try:
                raw_value = item.get(field) or ("{}" if field == "financials_json" else "[]")
                item[target] = json.loads(raw_value)
            except (TypeError, ValueError):
                item[target] = {} if field == "financials_json" else []
        results.append(item)
    return results


# ============================================================
# research_documents
# ============================================================

def create_research_document(connection, **fields):
    now_iso = now_kst().isoformat()
    company_names = list(dict.fromkeys(
        str(name).strip() for name in (fields.pop("company_names", None) or [])
        if str(name).strip()
    ))
    if not company_names and fields.get("company_name"):
        company_names = [fields["company_name"]]
    columns = (
        "company_name", "title", "publisher", "report_date", "original_filename",
        "stored_filename", "mime_type", "file_size", "sha256", "page_count",
        "extracted_text", "extraction_status", "uploaded_by", "created_at", "updated_at",
    )
    values = [fields.get(column) for column in columns]
    values[-2] = fields.get("created_at") or now_iso
    values[-1] = fields.get("updated_at") or now_iso
    cursor = connection.execute(
        f"INSERT INTO research_documents ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        values,
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO research_document_companies
            (document_id, company_name, created_at)
        VALUES (?, ?, ?)
        """,
        [(cursor.lastrowid, name, now_iso) for name in company_names],
    )
    connection.commit()
    return cursor.lastrowid


def _decode_research_document(row):
    if not row:
        return None
    item = dict(row)
    company_names = [
        name for name in str(item.get("company_names_csv") or "").split("\x1f")
        if name
    ]
    item["company_names"] = company_names or [item["company_name"]]
    for field in ("key_points_json", "risks_json"):
        target = field.removesuffix("_json")
        try:
            item[target] = json.loads(item.get(field) or "[]")
        except (TypeError, ValueError):
            item[target] = []
    return item


def get_research_document(connection, document_id):
    row = connection.execute(
        """
        SELECT d.*, (
            SELECT GROUP_CONCAT(company_name, char(31))
            FROM research_document_companies rc WHERE rc.document_id=d.id
        ) AS company_names_csv
        FROM research_documents d WHERE d.id = ?
        """,
        (document_id,),
    ).fetchone()
    return _decode_research_document(row)


def find_research_document_by_hash(connection, company_name, sha256):
    row = connection.execute(
        "SELECT * FROM research_documents WHERE company_name = ? AND sha256 = ?",
        (company_name, sha256),
    ).fetchone()
    return _decode_research_document(row)


def list_research_documents(connection, company_name=None, limit=200):
    where = ""
    params = []
    if company_name:
        where = """
        WHERE EXISTS (
            SELECT 1 FROM research_document_companies rc
            WHERE rc.document_id=d.id AND rc.company_name=?
        )
        """
        params.append(company_name)
    params.append(max(1, int(limit)))
    rows = connection.execute(
        f"""
        SELECT d.*, (
            SELECT GROUP_CONCAT(company_name, char(31))
            FROM research_document_companies rc WHERE rc.document_id=d.id
        ) AS company_names_csv
        FROM research_documents d
        {where}
        ORDER BY COALESCE(report_date, substr(created_at, 1, 10)) DESC, created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_decode_research_document(row) for row in rows]


def update_research_document_analysis(connection, document_id, analysis=None, error_message=None):
    analysis = analysis or {}
    now_iso = now_kst().isoformat()
    connection.execute(
        """
        UPDATE research_documents
        SET ai_summary = ?, investment_stance = ?, target_price = ?,
            key_points_json = ?, risks_json = ?, analyzed_at = ?,
            error_message = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            analysis.get("ai_summary"),
            analysis.get("investment_stance"),
            analysis.get("target_price"),
            json.dumps(analysis.get("key_points") or [], ensure_ascii=False),
            json.dumps(analysis.get("risks") or [], ensure_ascii=False),
            now_iso if analysis else None,
            error_message,
            now_iso,
            document_id,
        ),
    )
    connection.commit()


def delete_research_document(connection, document_id):
    connection.execute("DELETE FROM research_documents WHERE id = ?", (document_id,))
    connection.commit()


def search_research_documents(connection, term, days=365, limit=100):
    pattern = f"%{term}%"
    rows = connection.execute(
        """
        SELECT d.*, (
            SELECT GROUP_CONCAT(company_name, char(31))
            FROM research_document_companies rc WHERE rc.document_id=d.id
        ) AS company_names_csv
        FROM research_documents d
        WHERE d.created_at >= datetime('now', ?)
          AND (
              EXISTS (
                  SELECT 1 FROM research_document_companies rc
                  WHERE rc.document_id=d.id AND rc.company_name LIKE ?
              )
              OR d.title LIKE ? OR d.publisher LIKE ?
              OR d.ai_summary LIKE ? OR d.extracted_text LIKE ?
          )
        ORDER BY COALESCE(d.report_date, substr(d.created_at, 1, 10)) DESC
        LIMIT ?
        """,
        (f"-{int(days)} days", pattern, pattern, pattern, pattern, pattern, int(limit)),
    ).fetchall()
    return [_decode_research_document(row) for row in rows]


# ============================================================
# dart_disclosures / disclosure_analysis
# ============================================================

def disclosure_exists(connection, rcept_no):
    row = connection.execute(
        "SELECT 1 FROM dart_disclosures WHERE rcept_no = ?", (rcept_no,)
    ).fetchone()
    return row is not None


def save_disclosure(connection, rcept_no, corp_name, dart_corp_code, report_nm,
                     pblntf_ty, rcept_dt, flr_nm, dart_link, is_important):
    connection.execute(
        """
        INSERT OR IGNORE INTO dart_disclosures (
            rcept_no, corp_name, dart_corp_code, report_nm, pblntf_ty, rcept_dt,
            flr_nm, dart_link, is_important, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rcept_no, corp_name, dart_corp_code, report_nm, pblntf_ty, rcept_dt,
            flr_nm, dart_link, 1 if is_important else 0, now_kst().isoformat(),
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT id FROM dart_disclosures WHERE rcept_no = ?", (rcept_no,)
    ).fetchone()
    return row["id"] if row else None


def mark_disclosure_alert_sent(connection, disclosure_id):
    connection.execute(
        "UPDATE dart_disclosures SET telegram_alert_sent_at = ? WHERE id = ?",
        (now_kst().isoformat(), disclosure_id),
    )
    connection.commit()


def list_recent_disclosures(connection, days=7, important_only=False):
    query = "SELECT * FROM dart_disclosures WHERE rcept_dt >= date('now', ?)"
    params = [f"-{days} days"]
    if important_only:
        query += " AND is_important = 1"
    query += " ORDER BY rcept_dt DESC"
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def list_disclosures_for_company(connection, company_name, dart_corp_code=None, days=90):
    clauses = ["rcept_dt >= date('now', ?)"]
    params = [f"-{max(1, int(days))} days"]
    if dart_corp_code:
        clauses.append("(dart_corp_code = ? OR corp_name LIKE ?)")
        params.extend([dart_corp_code, f"%{company_name}%"])
    else:
        clauses.append("corp_name LIKE ?")
        params.append(f"%{company_name}%")
    rows = connection.execute(
        f"SELECT * FROM dart_disclosures WHERE {' AND '.join(clauses)} "
        "ORDER BY rcept_dt DESC LIMIT 100",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def search_disclosures(connection, term, days=365, limit=100):
    like = f"%{term}%"
    rows = connection.execute(
        """
        SELECT d.*, a.ai_summary, a.importance, a.financial_impact,
               a.competitive_impact, a.risk_category
        FROM dart_disclosures d
        LEFT JOIN disclosure_analysis a ON a.id = (
            SELECT id FROM disclosure_analysis
            WHERE disclosure_id = d.id ORDER BY id DESC LIMIT 1
        )
        WHERE d.rcept_dt >= date('now', ?)
          AND (
            d.corp_name LIKE ? OR d.report_nm LIKE ? OR d.flr_nm LIKE ?
            OR a.ai_summary LIKE ? OR a.financial_impact LIKE ?
            OR a.competitive_impact LIKE ? OR a.risk_category LIKE ?
          )
        ORDER BY d.rcept_dt DESC LIMIT ?
        """,
        (f"-{max(1, int(days))} days", like, like, like, like, like, like, like, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def save_disclosure_analysis(connection, disclosure_id, ai_summary, importance,
                              financial_impact, competitive_impact, risk_category,
                              needs_executive_review, prompt_version, error_message=None):
    connection.execute(
        """
        INSERT INTO disclosure_analysis (
            disclosure_id, ai_summary, importance, financial_impact, competitive_impact,
            risk_category, needs_executive_review, prompt_version, analyzed_at, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            disclosure_id, ai_summary, importance, financial_impact, competitive_impact,
            risk_category, 1 if needs_executive_review else 0, prompt_version,
            now_kst().isoformat(), error_message,
        ),
    )
    connection.commit()


def get_disclosure_analysis(connection, disclosure_id):
    row = connection.execute(
        "SELECT * FROM disclosure_analysis WHERE disclosure_id = ? ORDER BY id DESC LIMIT 1",
        (disclosure_id,),
    ).fetchone()
    return dict(row) if row else None


# ============================================================
# monitored_laws / law_updates / law_analysis
# ============================================================

def list_monitored_laws(connection, active_only=True):
    query = "SELECT * FROM monitored_laws"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY law_name"
    return [dict(row) for row in connection.execute(query).fetchall()]


def upsert_monitored_law(connection, law_name, law_id=None, mst=None, active=True, notes=None):
    connection.execute(
        """
        INSERT INTO monitored_laws (law_name, law_id, mst, active, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(law_name) DO UPDATE SET
            law_id = excluded.law_id, mst = excluded.mst, active = excluded.active
        """,
        (law_name, law_id, mst, 1 if active else 0, notes, now_kst().isoformat()),
    )
    connection.commit()


def get_latest_law_snapshot_hash(connection, monitored_law_id):
    row = connection.execute(
        "SELECT snapshot_hash FROM law_updates WHERE monitored_law_id = ? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (monitored_law_id,),
    ).fetchone()
    return row["snapshot_hash"] if row else None


def save_law_update(connection, monitored_law_id, snapshot_hash, effective_date,
                     promulgation_date, status, raw_summary):
    cursor = connection.execute(
        """
        INSERT INTO law_updates (
            monitored_law_id, snapshot_hash, effective_date, promulgation_date,
            status, raw_summary_json, fetched_at, is_new
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            monitored_law_id, snapshot_hash, effective_date, promulgation_date, status,
            json.dumps(raw_summary, ensure_ascii=False) if raw_summary is not None else None,
            now_kst().isoformat(),
        ),
    )
    connection.commit()
    return cursor.lastrowid


def list_recent_law_updates(connection, days=30):
    rows = connection.execute(
        "SELECT law_updates.*, monitored_laws.law_name AS law_name "
        "FROM law_updates JOIN monitored_laws ON monitored_laws.id = law_updates.monitored_law_id "
        "WHERE law_updates.fetched_at >= datetime('now', ?) "
        "ORDER BY law_updates.fetched_at DESC",
        (f"-{days} days",),
    ).fetchall()
    return [dict(row) for row in rows]


def search_law_updates(connection, term, days=365, limit=100):
    like = f"%{term}%"
    rows = connection.execute(
        """
        SELECT u.*, l.law_name, a.ai_summary, a.affected_scope,
               a.company_impact, a.action_needed
        FROM law_updates u
        JOIN monitored_laws l ON l.id = u.monitored_law_id
        LEFT JOIN law_analysis a ON a.id = (
            SELECT id FROM law_analysis
            WHERE law_update_id = u.id ORDER BY id DESC LIMIT 1
        )
        WHERE u.fetched_at >= datetime('now', ?)
          AND (
            l.law_name LIKE ? OR u.status LIKE ? OR u.raw_summary_json LIKE ?
            OR a.ai_summary LIKE ? OR a.affected_scope LIKE ?
            OR a.company_impact LIKE ? OR a.action_needed LIKE ?
          )
        ORDER BY u.fetched_at DESC LIMIT ?
        """,
        (f"-{max(1, int(days))} days", like, like, like, like, like, like, like, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def search_performance_reports(connection, term, days=365, limit=100):
    like = f"%{term}%"
    rows = connection.execute(
        """
        SELECT * FROM performance_reports
        WHERE received_at >= datetime('now', ?)
          AND (raw_text LIKE ? OR parsed_json LIKE ? OR header_type LIKE ?)
        ORDER BY received_at DESC LIMIT ?
        """,
        (f"-{max(1, int(days))} days", like, like, like, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def search_action_items(connection, term, days=365, limit=100):
    like = f"%{term}%"
    rows = connection.execute(
        """
        SELECT * FROM action_items
        WHERE created_at >= datetime('now', ?)
          AND (
            title LIKE ? OR description LIKE ? OR owner LIKE ? OR memo LIKE ?
            OR ai_recommended_action LIKE ? OR source_type LIKE ?
          )
        ORDER BY updated_at DESC LIMIT ?
        """,
        (f"-{max(1, int(days))} days", like, like, like, like, like, like, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def search_executive_insights(connection, term, days=365, limit=100):
    like = f"%{term}%"
    rows = connection.execute(
        """
        SELECT * FROM executive_insights
        WHERE created_at >= datetime('now', ?)
          AND (
            title LIKE ? OR evidence_json LIKE ? OR facts LIKE ?
            OR ai_interpretation LIKE ? OR expected_impact LIKE ?
            OR recommended_action LIKE ? OR category LIKE ?
          )
        ORDER BY created_at DESC LIMIT ?
        """,
        (f"-{max(1, int(days))} days", like, like, like, like, like, like, like, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def save_law_analysis(connection, law_update_id, ai_summary, affected_scope,
                       company_impact, action_needed, prompt_version, error_message=None):
    connection.execute(
        """
        INSERT INTO law_analysis (
            law_update_id, ai_summary, affected_scope, company_impact, action_needed,
            prompt_version, analyzed_at, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            law_update_id, ai_summary, affected_scope, company_impact, action_needed,
            prompt_version, now_kst().isoformat(), error_message,
        ),
    )
    connection.commit()


# ============================================================
# dashboard_analysis_runs
# ============================================================

def start_analysis_run(connection, run_type, prompt_version=None, input_hash=None):
    cursor = connection.execute(
        """
        INSERT INTO dashboard_analysis_runs (run_type, started_at, status, prompt_version, input_hash)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (run_type, now_kst().isoformat(), prompt_version, input_hash),
    )
    connection.commit()
    return cursor.lastrowid


def finish_analysis_run(connection, run_id, status, error_message=None):
    connection.execute(
        "UPDATE dashboard_analysis_runs SET finished_at = ?, status = ?, error_message = ? WHERE id = ?",
        (now_kst().isoformat(), status, error_message, run_id),
    )
    connection.commit()


def get_last_successful_run(connection, run_type):
    row = connection.execute(
        "SELECT * FROM dashboard_analysis_runs WHERE run_type = ? AND status = 'success' "
        "ORDER BY finished_at DESC LIMIT 1",
        (run_type,),
    ).fetchone()
    return dict(row) if row else None


# ============================================================
# api_usage / errors (대시보드 자체 AI 호출 비용 보호 + 오류 로그)
# ============================================================

def record_api_usage(connection, model, request_type, input_tokens, output_tokens, estimated_cost, success):
    connection.execute(
        """
        INSERT INTO api_usage (called_at, model, request_type, input_tokens, output_tokens, estimated_cost, success)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (now_kst().isoformat(), model, request_type, input_tokens, output_tokens, estimated_cost, 1 if success else 0),
    )
    connection.commit()


def get_today_usage_summary(connection):
    today_prefix = now_kst().strftime("%Y-%m-%d")
    row = connection.execute(
        "SELECT COUNT(*) AS call_count, COALESCE(SUM(estimated_cost), 0) AS total_cost "
        "FROM api_usage WHERE called_at LIKE ?",
        (f"{today_prefix}%",),
    ).fetchone()
    return {"call_count": row["call_count"], "total_cost": row["total_cost"]}


def log_error(connection, stage, error_type, error_message):
    connection.execute(
        "INSERT INTO errors (occurred_at, stage, error_type, error_message) VALUES (?, ?, ?, ?)",
        (now_kst().isoformat(), stage, error_type, (error_message or "")[:2000]),
    )
    connection.commit()
