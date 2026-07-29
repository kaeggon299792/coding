"""
dashboard.db에 대한 CRUD 함수 모음.

기존 database.py들과 동일하게 sqlite3.Row 기반 함수형 스타일을 따른다.
AI가 생성한 내용(ai_suggested=1 등)과 사용자가 직접 입력/승인한 내용을
필드로 명확히 구분한다.
"""

import json
import re

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
    connection.execute("DELETE FROM action_item_comments WHERE action_item_id = ?", (item_id,))
    connection.execute("DELETE FROM action_items WHERE id = ?", (item_id,))
    connection.commit()


def list_action_item_comments(connection, item_id):
    rows = connection.execute(
        """
        SELECT c.*, u.username AS author_name
        FROM action_item_comments c
        JOIN dashboard_users u ON u.id = c.author_id
        WHERE c.action_item_id = ? AND c.is_deleted = 0
        ORDER BY c.created_at ASC, c.id ASC
        """,
        (item_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_action_item_comment(connection, comment_id):
    row = connection.execute(
        """
        SELECT c.*, u.username AS author_name
        FROM action_item_comments c
        JOIN dashboard_users u ON u.id = c.author_id
        WHERE c.id = ?
        """,
        (comment_id,),
    ).fetchone()
    return dict(row) if row else None


def create_action_item_comment(connection, item_id, author_id, content):
    content = (content or "").strip()
    if not content:
        raise ValueError("댓글 내용을 입력해주세요.")
    if len(content) > 1000:
        raise ValueError("댓글은 1,000자 이하로 입력해주세요.")
    now_iso = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO action_item_comments
            (action_item_id, author_id, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (item_id, author_id, content, now_iso, now_iso),
    )
    connection.commit()
    return cursor.lastrowid


def update_action_item_comment(connection, comment_id, content):
    content = (content or "").strip()
    if not content:
        raise ValueError("댓글 내용을 입력해주세요.")
    if len(content) > 1000:
        raise ValueError("댓글은 1,000자 이하로 입력해주세요.")
    connection.execute(
        """
        UPDATE action_item_comments SET content = ?, updated_at = ?
        WHERE id = ? AND is_deleted = 0
        """,
        (content, now_kst().isoformat(timespec="seconds"), comment_id),
    )
    connection.commit()


def delete_action_item_comment(connection, comment_id, user_id):
    now_iso = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """
        UPDATE action_item_comments
        SET is_deleted = 1, deleted_at = ?, deleted_by = ?, updated_at = ?
        WHERE id = ? AND is_deleted = 0
        """,
        (now_iso, user_id, now_iso, comment_id),
    )
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

def _performance_number(value):
    if value is None:
        return None
    match = re.search(r"-?[\d,]+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _with_performance_visual(item):
    parsed = item.get("parsed") or {}
    group = _performance_number(parsed.get("group_sales_today"))
    casino = _performance_number(parsed.get("casino_sales"))
    hotel = _performance_number(parsed.get("hotel_resort_sales"))
    change = _performance_number(parsed.get("change_percent"))
    values = [abs(value) for value in (group, casino, hotel) if value is not None]
    scale = max(values, default=1) or 1
    item["visual"] = {
        "group": group,
        "casino": casino,
        "hotel": hotel,
        "change": change,
        "group_width": min(abs(group or 0) / scale * 100, 100),
        "casino_width": min(abs(casino or 0) / scale * 100, 100),
        "hotel_width": min(abs(hotel or 0) / scale * 100, 100),
    }
    return item


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
        results.append(_with_performance_visual(item))
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
    return _with_performance_visual(item)


def get_casino_sales_trend(connection, end_date, days=30):
    rows = connection.execute(
        """
        SELECT report_date, received_at, parsed_json
        FROM performance_reports
        WHERE parsing_status = 'ok'
          AND report_date BETWEEN date(?, ?) AND date(?)
        ORDER BY report_date ASC, received_at DESC
        """,
        (end_date, f"-{max(days - 1, 0)} days", end_date),
    ).fetchall()

    # 하루에 여러 차례 수신된 경우 가장 마지막 실적만 사용한다.
    daily = {}
    for row in rows:
        if row["report_date"] in daily:
            continue
        try:
            parsed = json.loads(row["parsed_json"]) if row["parsed_json"] else {}
        except (ValueError, TypeError):
            continue
        value = _performance_number(parsed.get("casino_sales"))
        if value is not None:
            daily[row["report_date"]] = value

    entries = [
        {"date": report_date, "label": report_date[5:].replace("-", "."), "value": value}
        for report_date, value in daily.items()
    ]
    if not entries:
        return None

    values = [entry["value"] for entry in entries]
    low = min(values + [0])
    high = max(values + [0])
    if high == low:
        high = low + 1
    value_range = high - low
    left, right, top, bottom = 42.0, 958.0, 24.0, 224.0
    width = right - left
    height = bottom - top
    denominator = max(len(entries) - 1, 1)
    for index, entry in enumerate(entries):
        entry["x"] = left + (index / denominator) * width
        entry["y"] = top + ((high - entry["value"]) / value_range) * height

    zero_y = top + ((high - 0) / value_range) * height
    latest = entries[-1]
    return {
        "entries": entries,
        "points": " ".join(f'{entry["x"]:.1f},{entry["y"]:.1f}' for entry in entries),
        "zero_y": zero_y,
        "latest": latest,
        "highest": max(entries, key=lambda item: item["value"]),
        "lowest": min(entries, key=lambda item: item["value"]),
        "start_date": entries[0]["date"],
        "end_date": latest["date"],
        "day_count": len(entries),
    }


# ============================================================
# tourism_visitor_stats
# ============================================================

TOURISM_CATEGORIES = ["중국", "일본", "대만", "몽골", "기타"]


def upsert_tourism_stat(connection, ym, nat_label, visitor_count):
    now = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO tourism_visitor_stats
            (ym, nat_label, visitor_count, fetched_at, changed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ym, nat_label) DO UPDATE SET
            changed_at = CASE
                WHEN tourism_visitor_stats.visitor_count != excluded.visitor_count
                THEN excluded.changed_at ELSE tourism_visitor_stats.changed_at END,
            visitor_count = excluded.visitor_count,
            fetched_at = excluded.fetched_at
        """,
        (ym, nat_label, visitor_count, now, now),
    )
    connection.commit()


def list_tourism_yms(connection):
    rows = connection.execute(
        "SELECT DISTINCT ym FROM tourism_visitor_stats ORDER BY ym DESC"
    ).fetchall()
    return [row["ym"] for row in rows]


def get_tourism_ytd_comparison(connection):
    """올해 실제 누계와 작년 동기간을 비교하고 미발표 월을 추정한다."""
    yms = list_tourism_yms(connection)
    if not yms:
        return None

    latest_ym = yms[0]
    latest_year = int(latest_ym[:4])
    latest_month = int(latest_ym[4:6])
    this_year_yms = [f"{latest_year}{month:02d}" for month in range(1, 13)]
    actual_yms = this_year_yms[:latest_month]
    last_year_yms = [f"{latest_year - 1}{month:02d}" for month in range(1, 13)]
    target_yms = this_year_yms + last_year_yms
    placeholders = ",".join("?" for _ in target_yms)
    rows = connection.execute(
        f"""
        SELECT ym, nat_label, visitor_count, fetched_at
        FROM tourism_visitor_stats
        WHERE ym IN ({placeholders})
        """,
        target_yms,
    ).fetchall()

    monthly = {label: {"this": {}, "last": {}} for label in TOURISM_CATEGORIES}
    this_set, last_set, present = set(actual_yms), set(last_year_yms), set()
    latest_fetched_at = None
    for row in rows:
        present.add(row["ym"])
        latest_fetched_at = max(latest_fetched_at or "", row["fetched_at"] or "")
        if row["nat_label"] not in monthly:
            continue
        if row["ym"] in this_set:
            monthly[row["nat_label"]]["this"][int(row["ym"][4:])] = row["visitor_count"]
        elif row["ym"] in last_set:
            monthly[row["nat_label"]]["last"][int(row["ym"][4:])] = row["visitor_count"]

    categories = []
    for label in TOURISM_CATEGORIES:
        this_monthly = monthly[label]["this"]
        last_monthly = monthly[label]["last"]
        this_value = sum(this_monthly.values())
        last_value = sum(last_monthly.get(month, 0) for month in range(1, latest_month + 1))
        change_rate = (
            round((this_value - last_value) / last_value * 100, 1)
            if last_value else None
        )
        yoy_growth = (this_value / last_value) if last_value else 1.0
        ratios = [
            this_monthly[month] / last_monthly[month]
            for month in range(1, latest_month + 1)
            if month in this_monthly and last_monthly.get(month, 0) > 0
        ]
        recent_ratio = sum(ratios[-3:]) / len(ratios[-3:]) if ratios else yoy_growth
        trend_factor = recent_ratio / yoy_growth if yoy_growth else 1.0
        trend_factor = min(max(trend_factor, 0.7), 1.3)
        forecast = {
            month: round(last_monthly[month] * yoy_growth * trend_factor)
            for month in range(latest_month + 1, 13)
            if month in last_monthly
        }
        chart_max = max(
            [*last_monthly.values(), *this_monthly.values(), *forecast.values(), 1]
        )
        left, right, top, bottom = 22.0, 578.0, 18.0, 176.0
        month_x = lambda month: left + ((month - 1) / 11) * (right - left)
        value_y = lambda value: bottom - (value / chart_max) * (bottom - top)
        last_points = " ".join(
            f"{month_x(month):.1f},{value_y(last_monthly[month]):.1f}"
            for month in sorted(last_monthly)
        )
        actual_points = " ".join(
            f"{month_x(month):.1f},{value_y(this_monthly[month]):.1f}"
            for month in sorted(this_monthly)
        )
        forecast_series = {}
        if this_monthly:
            final_actual_month = max(this_monthly)
            forecast_series[final_actual_month] = this_monthly[final_actual_month]
        forecast_series.update(forecast)
        forecast_points = " ".join(
            f"{month_x(month):.1f},{value_y(forecast_series[month]):.1f}"
            for month in sorted(forecast_series)
        )
        categories.append({
            "label": label,
            "this_value": this_value,
            "last_value": last_value,
            "difference": this_value - last_value,
            "change_rate": change_rate,
            "yoy_growth": yoy_growth,
            "trend_factor": trend_factor,
            "projected_total": this_value + sum(forecast.values()),
            "last_annual_total": sum(last_monthly.values()),
            "last_points": last_points,
            "actual_points": actual_points,
            "forecast_points": forecast_points,
            "this_monthly": this_monthly,
            "last_monthly": last_monthly,
            "forecast": forecast,
        })

    total_this_monthly = {
        month: sum(item["this_monthly"].get(month, 0) for item in categories)
        for month in range(1, latest_month + 1)
    }
    total_last_monthly = {
        month: sum(item["last_monthly"].get(month, 0) for item in categories)
        for month in range(1, 13)
    }
    total_forecast = {
        month: sum(item["forecast"].get(month, 0) for item in categories)
        for month in range(latest_month + 1, 13)
    }
    total_chart_max = max(
        [*total_last_monthly.values(), *total_this_monthly.values(), *total_forecast.values(), 1]
    )
    total_value_y = lambda value: bottom - (value / total_chart_max) * (bottom - top)
    total_last_points = " ".join(
        f"{month_x(month):.1f},{total_value_y(total_last_monthly[month]):.1f}"
        for month in sorted(total_last_monthly)
    )
    total_actual_points = " ".join(
        f"{month_x(month):.1f},{total_value_y(total_this_monthly[month]):.1f}"
        for month in sorted(total_this_monthly)
    )
    total_forecast_series = {}
    if total_this_monthly:
        final_actual_month = max(total_this_monthly)
        total_forecast_series[final_actual_month] = total_this_monthly[final_actual_month]
    total_forecast_series.update(total_forecast)
    total_forecast_points = " ".join(
        f"{month_x(month):.1f},{total_value_y(total_forecast_series[month]):.1f}"
        for month in sorted(total_forecast_series)
    )
    total_this_value = sum(total_this_monthly.values())
    total_last_value = sum(
        total_last_monthly.get(month, 0) for month in range(1, latest_month + 1)
    )
    total_category = {
        "label": "전체 관광객",
        "this_value": total_this_value,
        "last_value": total_last_value,
        "difference": total_this_value - total_last_value,
        "change_rate": (
            round((total_this_value - total_last_value) / total_last_value * 100, 1)
            if total_last_value else None
        ),
        "projected_total": total_this_value + sum(total_forecast.values()),
        "last_annual_total": sum(total_last_monthly.values()),
        "last_points": total_last_points,
        "actual_points": total_actual_points,
        "forecast_points": total_forecast_points,
    }

    actual_total = sum(item["this_value"] for item in categories)
    last_same_period_total = sum(item["last_value"] for item in categories)
    return {
        "categories": categories,
        "this_year": latest_year,
        "last_year": latest_year - 1,
        "period_label": f"1~{latest_month}월",
        "latest_ym": latest_ym,
        "complete": all(ym in present for ym in actual_yms + last_year_yms),
        "latest_fetched_at": latest_fetched_at,
        "this_total": actual_total,
        "last_total": last_same_period_total,
        "projected_total": sum(item["projected_total"] for item in categories),
        "last_annual_total": sum(item["last_annual_total"] for item in categories),
        "actual_month": latest_month,
        "total_category": total_category,
    }


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


def upsert_legislative_bill(connection, bill):
    existing = connection.execute(
        "SELECT id FROM legislative_bills WHERE bill_id = ?",
        (bill["bill_id"],),
    ).fetchone()
    now = now_kst().isoformat()
    connection.execute(
        """
        INSERT INTO legislative_bills (
            bill_id, bill_no, era, bill_kind, bill_name, proposer_kind,
            proposer_name, proposed_date, committee_name, committee_result,
            plenary_result, process_stage, pass_status, link_url, pdf_url,
            matched_keyword, first_seen_at, last_checked_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bill_id) DO UPDATE SET
            bill_no = excluded.bill_no,
            era = excluded.era,
            bill_kind = excluded.bill_kind,
            bill_name = excluded.bill_name,
            proposer_kind = excluded.proposer_kind,
            proposer_name = excluded.proposer_name,
            proposed_date = excluded.proposed_date,
            committee_name = excluded.committee_name,
            committee_result = excluded.committee_result,
            plenary_result = excluded.plenary_result,
            process_stage = excluded.process_stage,
            pass_status = excluded.pass_status,
            link_url = excluded.link_url,
            pdf_url = excluded.pdf_url,
            matched_keyword = excluded.matched_keyword,
            last_checked_at = excluded.last_checked_at,
            updated_at = excluded.updated_at
        """,
        (
            bill["bill_id"], bill.get("bill_no"), bill.get("era"),
            bill.get("bill_kind"), bill["bill_name"], bill.get("proposer_kind"),
            bill.get("proposer_name"), bill.get("proposed_date"),
            bill.get("committee_name"), bill.get("committee_result"),
            bill.get("plenary_result"), bill.get("process_stage"),
            bill.get("pass_status"), bill.get("link_url"), bill.get("pdf_url"),
            bill.get("matched_keyword"), now, now, now,
        ),
    )
    connection.commit()
    return existing is None


def list_legislative_bills(connection, limit=50):
    rows = connection.execute(
        """
        SELECT * FROM legislative_bills
        ORDER BY COALESCE(proposed_date, '') DESC, id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_pending_legislative_bill_analysis(connection, limit=10):
    rows = connection.execute(
        """
        SELECT * FROM legislative_bills
        WHERE analyzed_at IS NULL AND analysis_error IS NULL
        ORDER BY COALESCE(proposed_date, '') DESC, id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(row) for row in rows]


def save_legislative_bill_analysis(connection, bill_id, analysis=None, error=None, source=None):
    analysis = analysis or {}
    connection.execute(
        """
        UPDATE legislative_bills SET
            ai_summary = ?,
            impact_direction = ?,
            impact_level = ?,
            impact_reason = ?,
            action_needed = ?,
            analysis_source = ?,
            analyzed_at = ?,
            analysis_error = ?
        WHERE id = ?
        """,
        (
            analysis.get("ai_summary"),
            analysis.get("impact_direction"),
            analysis.get("impact_level"),
            analysis.get("impact_reason"),
            analysis.get("action_needed"),
            source,
            now_kst().isoformat() if analysis else None,
            error,
            bill_id,
        ),
    )
    connection.commit()


def upsert_market_quote(connection, quote):
    connection.execute(
        """
        INSERT INTO market_quotes (
            symbol, name, asset_type, market, base_date, close_price,
            change_value, change_rate, open_price, high_price, low_price,
            volume, market_cap, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            name = excluded.name,
            asset_type = excluded.asset_type,
            market = excluded.market,
            base_date = excluded.base_date,
            close_price = excluded.close_price,
            change_value = excluded.change_value,
            change_rate = excluded.change_rate,
            open_price = excluded.open_price,
            high_price = excluded.high_price,
            low_price = excluded.low_price,
            volume = excluded.volume,
            market_cap = excluded.market_cap,
            fetched_at = excluded.fetched_at
        """,
        (
            quote["symbol"], quote["name"], quote["asset_type"],
            quote.get("market"), quote.get("base_date"), quote.get("close_price"),
            quote.get("change_value"), quote.get("change_rate"),
            quote.get("open_price"), quote.get("high_price"), quote.get("low_price"),
            quote.get("volume"), quote.get("market_cap"), now_kst().isoformat(),
        ),
    )
    connection.commit()


def upsert_market_quote_history(connection, symbol, points):
    now = now_kst().isoformat()
    connection.executemany(
        """
        INSERT INTO market_quote_history (symbol, base_date, close_price, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(symbol, base_date) DO UPDATE SET
            close_price = excluded.close_price,
            fetched_at = excluded.fetched_at
        """,
        [
            (symbol, point["base_date"], point["close_price"], now)
            for point in points
            if point.get("base_date") and point.get("close_price") is not None
        ],
    )
    connection.commit()


def _market_sparkline(connection, symbol):
    rows = connection.execute(
        """
        SELECT base_date, close_price FROM market_quote_history
        WHERE symbol = ?
        ORDER BY base_date DESC LIMIT 30
        """,
        (symbol,),
    ).fetchall()
    values = [dict(row) for row in reversed(rows)]
    if len(values) < 2:
        return {"trend_points": "", "trend_area_points": "", "trend_count": len(values)}
    prices = [float(row["close_price"]) for row in values]
    low, high = min(prices), max(prices)
    spread = high - low or 1.0
    points = []
    for index, price in enumerate(prices):
        x = index / (len(prices) - 1) * 100
        y = 34 - ((price - low) / spread) * 28
        points.append(f"{x:.1f},{y:.1f}")
    point_string = " ".join(points)
    return {
        "trend_points": point_string,
        "trend_area_points": f"0,40 {point_string} 100,40",
        "trend_count": len(values),
    }


def list_market_quotes(connection):
    order = {"KOSPI": 0, "034230": 1, "114090": 2, "035250": 3, "032350": 4}
    rows = [dict(row) for row in connection.execute("SELECT * FROM market_quotes").fetchall()]
    for row in rows:
        row.update(_market_sparkline(connection, row["symbol"]))
        market_cap = row.get("market_cap")
        if market_cap:
            trillion, remainder = divmod(int(market_cap), 1_000_000_000_000)
            hundred_million = remainder // 100_000_000
            row["market_cap_label"] = (
                f"{trillion}조 {hundred_million:,}억원"
                if trillion
                else f"{hundred_million:,}억원"
            )
        else:
            row["market_cap_label"] = None
    return sorted(rows, key=lambda row: order.get(row["symbol"], 99))


def upsert_economic_observation(connection, item):
    now = now_kst().isoformat()
    connection.execute(
        """
        INSERT INTO economic_series (
            series_code, observation_date, label, category, value, unit, source,
            fetched_at, changed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(series_code, observation_date) DO UPDATE SET
            changed_at=CASE
                WHEN economic_series.value != excluded.value
                THEN excluded.changed_at ELSE economic_series.changed_at END,
            value=excluded.value, fetched_at=excluded.fetched_at
        """,
        (
            item["series_code"], item["observation_date"], item["label"],
            item["category"], item["value"], item["unit"], item["source"],
            now, now,
        ),
    )
    connection.commit()


def list_economic_series(connection, days=45):
    rows = connection.execute(
        "SELECT * FROM economic_series WHERE observation_date >= strftime('%Y%m%d','now',?) "
        "ORDER BY series_code, observation_date",
        (f"-{max(1, int(days))} days",),
    ).fetchall()
    grouped = {}
    for raw in rows:
        row = dict(raw)
        grouped.setdefault(row["series_code"], []).append(row)
    order = ("OIL_B027", "OIL_D047", "OIL_K015", "FX_USD", "FX_JPY100", "FX_CNH", "FX_EUR")
    result = []
    for code in order:
        items = grouped.get(code, [])[-30:]
        if not items:
            continue
        values = [float(item["value"]) for item in items]
        low, high = min(values), max(values)
        spread = high - low or 1
        points = [
            f"{i / max(1, len(values)-1) * 100:.1f},{34 - (value-low)/spread*28:.1f}"
            for i, value in enumerate(values)
        ]
        point_string = " ".join(points)
        result.append({
            **items[-1], "points": point_string,
            "area_points": f"0,40 {point_string} 100,40",
            "count": len(items), "start_date": items[0]["observation_date"],
            "end_date": items[-1]["observation_date"], "latest": values[-1],
            "change": values[-1] - values[-2] if len(values) > 1 else 0,
        })
    return result


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


def list_recent_executive_insights(connection, days=365, limit=50):
    rows = connection.execute(
        """
        SELECT * FROM executive_insights
        WHERE created_at >= datetime('now', ?)
        ORDER BY created_at DESC LIMIT ?
        """,
        (f"-{max(1, int(days))} days", max(1, min(int(limit), 200))),
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


def get_latest_completed_run(connection, run_type):
    row = connection.execute(
        "SELECT * FROM dashboard_analysis_runs "
        "WHERE run_type = ? AND status != 'running' "
        "ORDER BY finished_at DESC LIMIT 1",
        (run_type,),
    ).fetchone()
    return dict(row) if row else None


def get_data_freshness(connection, table, checked_run_type, changed_column="changed_at"):
    allowed = {
        "tourism_visitor_stats": {"changed_at", "fetched_at"},
        "economic_series": {"changed_at", "fetched_at"},
        "dart_disclosures": {"fetched_at"},
        "law_updates": {"fetched_at"},
    }
    if table not in allowed or changed_column not in allowed[table]:
        raise ValueError("Unsupported freshness source")
    latest_run = get_latest_completed_run(connection, checked_run_type)
    row = connection.execute(
        f"SELECT MAX({changed_column}) AS changed_at FROM {table}"
    ).fetchone()
    return {
        "checked_at": latest_run.get("finished_at") if latest_run else None,
        "check_status": latest_run.get("status") if latest_run else None,
        "changed_at": row["changed_at"] if row else None,
    }


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
