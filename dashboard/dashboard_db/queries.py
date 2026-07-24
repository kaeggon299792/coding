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


def create_user(connection, username, password_hash):
    now_iso = now_kst().isoformat()
    cursor = connection.execute(
        "INSERT INTO dashboard_users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, now_iso),
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
):
    now_iso = now_kst().isoformat()
    cursor = connection.execute(
        """
        INSERT INTO action_items (
            title, description, source_type, source_ref_id, owner, created_at,
            due_date, due_date_confidence, priority, status, ai_suggested,
            approved_by_user, ai_recommended_action, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_started', ?, ?, ?, ?)
        """,
        (
            title, description, source_type, source_ref_id, owner, now_iso,
            due_date, due_date_confidence, priority,
            1 if ai_suggested else 0,
            0 if ai_suggested else 1,  # AI 제안은 기본 미승인 상태로 저장
            ai_recommended_action, now_iso,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def list_action_items(connection, status=None, only_pending_due=False):
    query = "SELECT * FROM action_items"
    params = []
    clauses = []
    if status:
        clauses.append("status = ?")
        params.append(status)
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


def count_action_items(connection, status=None, overdue_only=False, due_today_only=False):
    today = now_kst().strftime("%Y-%m-%d")
    query = "SELECT COUNT(*) AS c FROM action_items WHERE status != '완료' AND status != 'done'"
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
