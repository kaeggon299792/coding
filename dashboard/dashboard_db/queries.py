"""
dashboard.db에 대한 CRUD 함수 모음.

기존 database.py들과 동일하게 sqlite3.Row 기반 함수형 스타일을 따른다.
AI가 생성한 내용(ai_suggested=1 등)과 사용자가 직접 입력/승인한 내용을
필드로 명확히 구분한다.
"""

import json
import re
from datetime import datetime, timedelta

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


def purge_expired_withdrawn_users(connection):
    """Anonymize personal account data after the 14-day withdrawal hold."""

    now_iso = now_kst().isoformat()
    rows = connection.execute(
        """
        SELECT id, username
        FROM dashboard_users
        WHERE approval_status='withdrawal_pending'
          AND deletion_scheduled_at IS NOT NULL
          AND deletion_scheduled_at<=?
        """,
        (now_iso,),
    ).fetchall()
    for row in rows:
        user_id = row["id"]
        old_username = row["username"]
        anonymous_username = f"deleted-user-{user_id}"
        connection.execute(
            """
            UPDATE dashboard_users
            SET username=?, password_hash='!withdrawn', role='user', is_active=0,
                email=NULL, google_sub=NULL, name=NULL, picture_url=NULL,
                approval_status='deleted', landing_page='dashboard',
                updated_at=?, deleted_at=?
            WHERE id=?
            """,
            (anonymous_username, now_iso, now_iso, user_id),
        )
        connection.execute(
            "DELETE FROM dashboard_user_permissions WHERE user_id=?", (user_id,)
        )
        connection.execute(
            """
            UPDATE dashboard_active_sessions
            SET revoked_at=COALESCE(revoked_at, ?),
                revoke_reason=COALESCE(revoke_reason, 'withdrawal_retention_expired'),
                ip_address=NULL, user_agent=NULL
            WHERE user_id=?
            """,
            (now_iso, user_id),
        )
        connection.execute(
            "UPDATE dashboard_user_audit SET target_username=? WHERE target_user_id=?",
            (anonymous_username, user_id),
        )
        connection.execute(
            "UPDATE dashboard_user_audit SET actor_username=? WHERE actor_user_id=?",
            (anonymous_username, user_id),
        )
        connection.execute(
            """
            UPDATE security_audit_log
            SET username=?, ip_address=NULL, user_agent=NULL
            WHERE user_id=?
               OR (action='SELF_REGISTRATION' AND resource_id=?)
            """,
            (anonymous_username, user_id, str(user_id)),
        )
        # Business records remain available, but the withdrawn member's name is
        # replaced so their personal account identity is no longer exposed.
        for table, column in (
            ("action_items", "reported_by"),
            ("research_documents", "uploaded_by"),
            ("official_documents", "registered_by"),
            ("official_document_history", "actor"),
            ("official_document_change_log", "actor"),
            ("official_excel_exports", "exported_by"),
        ):
            connection.execute(
                f"UPDATE {table} SET {column}=? WHERE {column}=?",
                (anonymous_username, old_username),
            )
        connection.execute(
            "UPDATE community_posts SET author_username=? WHERE author_id=?",
            (anonymous_username, user_id),
        )
    if rows:
        connection.commit()
    return len(rows)


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
    feedback_type="일반 의견",
):
    now_iso = now_kst().isoformat()
    cursor = connection.execute(
        """
        INSERT INTO action_items (
            title, description, source_type, source_ref_id, owner, created_at,
            due_date, due_date_confidence, priority, status, ai_suggested,
            approved_by_user, ai_recommended_action, updated_at, reported_by,
            bug_page, environment, feedback_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title, description, source_type, source_ref_id, owner, now_iso,
            due_date, due_date_confidence, priority, status,
            1 if ai_suggested else 0,
            0 if ai_suggested else 1,  # AI 제안은 기본 미승인 상태로 저장
            ai_recommended_action, now_iso, reported_by, bug_page, environment,
            feedback_type,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def list_action_items(
    connection, status=None, only_pending_due=False, reported_by=None,
    source_type=None, exclude_source_type=None,
):
    query = "SELECT * FROM action_items"
    params = []
    clauses = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if reported_by is not None:
        clauses.append("reported_by = ?")
        params.append(reported_by)
    if source_type is not None:
        clauses.append("source_type = ?")
        params.append(source_type)
    if exclude_source_type is not None:
        clauses.append("source_type <> ?")
        params.append(exclude_source_type)
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


# ============================================================
# community_posts
# ============================================================

def create_community_post(
    connection, author_id, author_username, title, content,
    image_url=None, pdf_url=None, board_type="community", is_pinned=False,
):
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or len(title) > 150:
        raise ValueError("제목은 1~150자로 입력해주세요.")
    if not content or len(content) > 5000:
        raise ValueError("내용은 1~5,000자로 입력해주세요.")
    if board_type not in {"community", "notice"}:
        raise ValueError("올바르지 않은 게시판 종류입니다.")

    now = now_kst()
    ten_minutes_ago = (now - timedelta(minutes=10)).isoformat(timespec="seconds")
    day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
    recent_count = connection.execute(
        "SELECT COUNT(*) FROM community_posts WHERE author_id=? AND is_deleted=0 AND created_at>=?",
        (author_id, ten_minutes_ago),
    ).fetchone()[0]
    daily_count = connection.execute(
        "SELECT COUNT(*) FROM community_posts WHERE author_id=? AND is_deleted=0 AND created_at>=?",
        (author_id, day_ago),
    ).fetchone()[0]
    if recent_count >= 5 or daily_count >= 30:
        raise ValueError("글 작성 횟수가 너무 많습니다. 잠시 후 다시 시도해주세요.")

    now_iso = now.isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO community_posts
            (author_id, author_username, title, content, image_url, pdf_url,
             board_type, is_pinned, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            author_id, author_username, title, content,
            image_url or None, pdf_url or None, board_type,
            1 if is_pinned and board_type == "community" else 0,
            now_iso, now_iso,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def list_community_posts(
    connection, limit=20, offset=0, board_type="community",
):
    rows = connection.execute(
        """
        SELECT post.*,
               (SELECT COUNT(1) FROM community_post_recommendations AS recommendation
                WHERE recommendation.post_id = post.id) AS recommendation_count,
               (SELECT COUNT(1) FROM community_comments AS comment
                WHERE comment.post_id = post.id AND comment.is_deleted = 0) AS comment_count
        FROM community_posts AS post
        WHERE post.is_deleted = 0 AND post.board_type = ?
        ORDER BY post.is_pinned DESC, post.created_at DESC, post.id DESC
        LIMIT ? OFFSET ?
        """,
        (board_type, max(1, min(int(limit), 100)), max(0, int(offset))),
    ).fetchall()
    return [dict(row) for row in rows]


def count_community_posts(connection, board_type="community"):
    return connection.execute(
        "SELECT COUNT(*) FROM community_posts WHERE is_deleted=0 AND board_type=?",
        (board_type,),
    ).fetchone()[0]


def set_community_post_pinned(connection, post_id, is_pinned):
    now_iso = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        UPDATE community_posts
        SET is_pinned=?, updated_at=?
        WHERE id=? AND board_type='community' AND is_deleted=0
        """,
        (1 if is_pinned else 0, now_iso, post_id),
    )
    if not cursor.rowcount:
        raise ValueError("자유게시판 글을 찾을 수 없습니다.")
    connection.commit()


def get_community_post(connection, post_id, user_id=None):
    row = connection.execute(
        """
        SELECT post.*,
               (SELECT COUNT(1) FROM community_post_recommendations AS recommendation
                WHERE recommendation.post_id = post.id) AS recommendation_count,
               CASE WHEN ? IS NULL THEN 0 ELSE EXISTS(
                   SELECT 1 FROM community_post_recommendations AS mine
                   WHERE mine.post_id = post.id AND mine.user_id = ?
               ) END AS recommended_by_current_user
        FROM community_posts AS post
        WHERE post.id = ? AND post.is_deleted = 0
        """,
        (user_id, user_id, post_id),
    ).fetchone()
    return dict(row) if row else None


def record_unique_action_item_view(connection, item_id, viewer_hash):
    cursor = connection.execute(
        """INSERT OR IGNORE INTO action_item_views(action_item_id,viewer_hash,created_at)
           SELECT id,?,? FROM action_items WHERE id=?""",
        (str(viewer_hash)[:64], now_kst().isoformat(timespec="seconds"), item_id),
    )
    if cursor.rowcount:
        connection.execute(
            "UPDATE action_items SET view_count=view_count+1 WHERE id=?", (item_id,)
        )
        connection.commit()
        return True
    return False


def update_community_post(
    connection, post_id, title, content, image_url=None, pdf_url=None,
    is_pinned=None,
):
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or len(title) > 150:
        raise ValueError("제목은 1~150자로 입력해주세요.")
    if not content or len(content) > 5000:
        raise ValueError("내용은 1~5,000자로 입력해주세요.")
    post = get_community_post(connection, post_id)
    if not post:
        raise ValueError("게시글을 찾을 수 없습니다.")
    pinned = post["is_pinned"]
    if is_pinned is not None and post["board_type"] == "community":
        pinned = 1 if is_pinned else 0
    connection.execute(
        """UPDATE community_posts
           SET title=?,content=?,image_url=?,pdf_url=?,is_pinned=?,updated_at=?
           WHERE id=? AND is_deleted=0""",
        (
            title, content, image_url or None, pdf_url or None, pinned,
            now_kst().isoformat(timespec="seconds"), post_id,
        ),
    )
    connection.commit()


def get_admin_dashboard_metrics(connection, date_key):
    """Return the administrator overview counts in one database query."""
    row = connection.execute(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM dashboard_users
                WHERE SUBSTR(created_at, 1, 10) = ?
            ) AS new_members,
            (
                SELECT COUNT(*)
                FROM dashboard_users
                WHERE COALESCE(approval_status, 'approved')
                      NOT IN ('withdrawal_pending', 'deleted')
            ) AS total_members,
            (
                SELECT COUNT(*)
                FROM community_posts
                WHERE is_deleted = 0
                  AND SUBSTR(created_at, 1, 10) = ?
            ) + (
                SELECT COUNT(*)
                FROM action_items
                WHERE source_type = 'bug_report'
                  AND SUBSTR(created_at, 1, 10) = ?
            ) AS new_posts,
            (
                SELECT COUNT(*)
                FROM dashboard_users
                WHERE SUBSTR(deletion_requested_at, 1, 10) = ?
                   OR (
                        deletion_requested_at IS NULL
                        AND SUBSTR(deleted_at, 1, 10) = ?
                   )
            ) AS withdrawals
        """,
        (date_key, date_key, date_key, date_key, date_key),
    ).fetchone()
    return dict(row) if row else {
        "new_members": 0,
        "total_members": 0,
        "new_posts": 0,
        "withdrawals": 0,
    }


def get_admin_dashboard_activity(connection, date_key):
    """Return seven days of member and board activity for the admin chart."""
    rows = connection.execute(
        """
        WITH RECURSIVE days(day) AS (
            SELECT DATE(?, '-6 days')
            UNION ALL
            SELECT DATE(day, '+1 day') FROM days WHERE day < DATE(?)
        )
        SELECT
            day,
            (
                SELECT COUNT(*) FROM dashboard_users
                WHERE SUBSTR(created_at, 1, 10) = day
            ) AS new_members,
            (
                SELECT COUNT(*) FROM community_posts
                WHERE is_deleted = 0 AND SUBSTR(created_at, 1, 10) = day
            ) + (
                SELECT COUNT(*) FROM action_items
                WHERE source_type = 'bug_report'
                  AND SUBSTR(created_at, 1, 10) = day
            ) AS new_posts,
            (
                SELECT COUNT(*) FROM dashboard_users
                WHERE SUBSTR(deletion_requested_at, 1, 10) = day
                   OR (
                        deletion_requested_at IS NULL
                        AND SUBSTR(deleted_at, 1, 10) = day
                   )
            ) AS withdrawals
        FROM days
        ORDER BY day
        """,
        (date_key, date_key),
    ).fetchall()
    return [dict(row) for row in rows]


def record_unique_community_post_view(connection, post_id, viewer_hash):
    cursor = connection.execute(
        """INSERT OR IGNORE INTO community_post_views(post_id,viewer_hash,created_at)
           SELECT id,?,? FROM community_posts WHERE id=? AND is_deleted=0""",
        (str(viewer_hash)[:64], now_kst().isoformat(timespec="seconds"), post_id),
    )
    if cursor.rowcount:
        connection.execute(
            "UPDATE community_posts SET view_count=view_count+1 WHERE id=?",
            (post_id,),
        )
        connection.commit()
        return True
    return False


def toggle_community_post_recommendation(connection, post_id, user_id):
    if not get_community_post(connection, post_id):
        raise ValueError("게시글을 찾을 수 없습니다.")
    existing = connection.execute(
        "SELECT 1 FROM community_post_recommendations WHERE post_id=? AND user_id=?",
        (post_id, user_id),
    ).fetchone()
    if existing:
        connection.execute(
            "DELETE FROM community_post_recommendations WHERE post_id=? AND user_id=?",
            (post_id, user_id),
        )
        recommended = False
    else:
        connection.execute(
            "INSERT INTO community_post_recommendations (post_id, user_id, created_at) VALUES (?, ?, ?)",
            (post_id, user_id, now_kst().isoformat(timespec="seconds")),
        )
        recommended = True
    connection.commit()
    count = connection.execute(
        "SELECT COUNT(1) FROM community_post_recommendations WHERE post_id=?",
        (post_id,),
    ).fetchone()[0]
    return recommended, count


def create_community_comment(connection, post_id, author_id, author_username, content):
    content = (content or "").strip()
    if not content or len(content) > 1000:
        raise ValueError("댓글은 1~1,000자로 입력해주세요.")
    if not get_community_post(connection, post_id):
        raise ValueError("게시글을 찾을 수 없습니다.")

    now = now_kst()
    ten_minutes_ago = (now - timedelta(minutes=10)).isoformat(timespec="seconds")
    day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
    recent_count = connection.execute(
        "SELECT COUNT(*) FROM community_comments "
        "WHERE author_id=? AND is_deleted=0 AND created_at>=?",
        (author_id, ten_minutes_ago),
    ).fetchone()[0]
    daily_count = connection.execute(
        "SELECT COUNT(*) FROM community_comments "
        "WHERE author_id=? AND is_deleted=0 AND created_at>=?",
        (author_id, day_ago),
    ).fetchone()[0]
    if recent_count >= 10 or daily_count >= 100:
        raise ValueError("댓글 작성 횟수가 너무 많습니다. 잠시 후 다시 시도해주세요.")

    now_iso = now.isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO community_comments
            (post_id, author_id, author_username, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (post_id, author_id, author_username, content, now_iso, now_iso),
    )
    connection.commit()
    return cursor.lastrowid


def list_community_comments(connection, post_id):
    rows = connection.execute(
        """
        SELECT * FROM community_comments
        WHERE post_id=? AND is_deleted=0
        ORDER BY created_at ASC, id ASC
        """,
        (post_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_community_comment(connection, comment_id):
    row = connection.execute(
        "SELECT * FROM community_comments WHERE id=? AND is_deleted=0",
        (comment_id,),
    ).fetchone()
    return dict(row) if row else None


def soft_delete_community_comment(connection, comment_id, user_id):
    now_iso = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """
        UPDATE community_comments
        SET is_deleted=1, deleted_at=?, deleted_by=?, updated_at=?
        WHERE id=? AND is_deleted=0
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
    if parsed_data and parsing_status == "ok" and report_date:
        performance_fields = {
            "group_sales_today": ("그룹 매출", "백만원"),
            "group_sales_yesterday": ("그룹 전일 매출", "백만원"),
            "casino_sales": ("워커힐 카지노 매출", "백만원"),
            "hotel_resort_sales": ("호텔·리조트 매출", "백만원"),
            "change_percent": ("그룹 매출 증감률", "%"),
        }
        for field, (label, unit) in performance_fields.items():
            value = _performance_number(parsed_data.get(field))
            if value is None:
                continue
            key = f"performance.{field}"
            upsert_source_data_series(
                connection, series_key=key, category="경영실적", label=label,
                unit=unit, frequency="daily", aggregation="sum",
                source_name="PARADIAN 경영실적 봇", is_internal=True,
            )
            upsert_source_data_point(
                connection, series_key=key, observation_date=str(report_date)[:10],
                value=value, source_record_key=str(telegram_message_id),
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
    tourism_keys = {
        "중국": "china", "일본": "japan", "대만": "taiwan",
        "몽골": "mongolia", "기타": "other",
    }
    slug = tourism_keys.get(nat_label, re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(nat_label)).strip("_").lower())
    key = f"tourism.visitors.{slug}"
    observation_date = f"{str(ym)[:4]}-{str(ym)[4:6]}-01"
    upsert_source_data_series(
        connection, series_key=key, category="관광객", label=f"{nat_label} 관광객",
        unit="명", frequency="monthly", aggregation="sum",
        source_name="한국문화관광연구원",
    )
    upsert_source_data_point(
        connection, series_key=key, observation_date=observation_date,
        value=visitor_count, source_record_key=f"{ym}:{nat_label}",
    )
    total = connection.execute(
        "SELECT SUM(visitor_count) AS total FROM tourism_visitor_stats WHERE ym=?",
        (ym,),
    ).fetchone()["total"]
    upsert_source_data_series(
        connection, series_key="tourism.visitors.total", category="관광객",
        label="전체 관광객", unit="명", frequency="monthly", aggregation="sum",
        source_name="한국문화관광연구원",
    )
    upsert_source_data_point(
        connection, series_key="tourism.visitors.total",
        observation_date=observation_date, value=total,
        source_record_key=f"{ym}:total",
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


def list_latest_company_executive_profiles(connection, company_name):
    """Return every representative from the company's latest profile date."""
    rows = connection.execute(
        """
        SELECT *
        FROM company_executive_profiles
        WHERE company_name = ?
          AND profile_as_of = (
              SELECT MAX(profile_as_of)
              FROM company_executive_profiles
              WHERE company_name = ?
          )
        ORDER BY id
        """,
        (company_name, company_name),
    ).fetchall()
    return [dict(row) for row in rows]


def list_company_benefits(connection, company_name=None):
    sql = "SELECT * FROM company_benefits"
    params = ()
    if company_name:
        sql += " WHERE company_name=?"
        params = (company_name,)
    sql += (
        " ORDER BY company_name, CASE WHEN ended_on IS NULL THEN 0 ELSE 1 END, "
        "category, benefit_name COLLATE NOCASE, COALESCE(ended_on, '') DESC"
    )
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def get_company_benefit(connection, benefit_id):
    row = connection.execute(
        "SELECT * FROM company_benefits WHERE id=?", (benefit_id,)
    ).fetchone()
    return dict(row) if row else None


def soft_delete_community_post(connection, post_id, user_id):
    now_iso = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        UPDATE community_posts
        SET is_deleted=1, deleted_at=?, deleted_by=?, updated_at=?
        WHERE id=? AND is_deleted=0
        """,
        (now_iso, user_id, now_iso, post_id),
    )
    if not cursor.rowcount:
        raise ValueError("게시글을 찾을 수 없습니다.")
    connection.commit()


def create_company_benefit(connection, values, actor_id=None):
    timestamp = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO company_benefits (
            company_name, category, benefit_name, support_value, benefit_level,
            notes, effective_from, ended_on, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["company_name"], values["category"], values["benefit_name"],
            values["support_value"], values["benefit_level"], values["notes"],
            values["effective_from"], values["ended_on"], actor_id, timestamp, timestamp,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def update_company_benefit(connection, benefit_id, values):
    cursor = connection.execute(
        """
        UPDATE company_benefits SET
            company_name=?, category=?, benefit_name=?, support_value=?,
            benefit_level=?, notes=?, effective_from=?, ended_on=?, updated_at=?
        WHERE id=?
        """,
        (
            values["company_name"], values["category"], values["benefit_name"],
            values["support_value"], values["benefit_level"], values["notes"],
            values["effective_from"], values["ended_on"],
            now_kst().isoformat(timespec="seconds"), benefit_id,
        ),
    )
    if not cursor.rowcount:
        raise ValueError("복리후생 항목을 찾을 수 없습니다.")
    connection.commit()


def end_company_benefit(connection, benefit_id, ended_on):
    cursor = connection.execute(
        """UPDATE company_benefits
           SET ended_on=?, updated_at=? WHERE id=? AND ended_on IS NULL""",
        (ended_on, now_kst().isoformat(timespec="seconds"), benefit_id),
    )
    if not cursor.rowcount:
        raise ValueError("활성 복리후생 항목을 찾을 수 없습니다.")
    connection.commit()


def list_company_recruitment_guides(connection, company_name=None, process_type=None):
    conditions = []
    params = []
    if company_name:
        conditions.append("company_name=?")
        params.append(company_name)
    if process_type:
        conditions.append("process_type=?")
        params.append(process_type)
    sql = "SELECT * FROM company_recruitment_guides"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY company_name, experience_period DESC, id DESC"
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def get_company_recruitment_guide(connection, guide_id):
    row = connection.execute(
        "SELECT * FROM company_recruitment_guides WHERE id=?", (guide_id,)
    ).fetchone()
    return dict(row) if row else None


def create_company_recruitment_guide(connection, values, actor_id=None):
    timestamp = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO company_recruitment_guides (
            company_name, process_type, position_name, stage_name, question_text,
            atmosphere, experience_period, notes, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["company_name"], values["process_type"], values["position_name"],
            values["stage_name"], values["question_text"], values["atmosphere"],
            values["experience_period"], values["notes"], actor_id,
            timestamp, timestamp,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def update_company_recruitment_guide(connection, guide_id, values):
    cursor = connection.execute(
        """
        UPDATE company_recruitment_guides SET
            company_name=?, process_type=?, position_name=?, stage_name=?,
            question_text=?, atmosphere=?, experience_period=?, notes=?, updated_at=?
        WHERE id=?
        """,
        (
            values["company_name"], values["process_type"], values["position_name"],
            values["stage_name"], values["question_text"], values["atmosphere"],
            values["experience_period"], values["notes"],
            now_kst().isoformat(timespec="seconds"), guide_id,
        ),
    )
    if not cursor.rowcount:
        raise ValueError("채용 족보 항목을 찾을 수 없습니다.")
    connection.commit()


def _company_comment_target_exists(connection, target_type, target_id):
    tables = {
        "benefit": "company_benefits",
        "recruitment_guide": "company_recruitment_guides",
    }
    table = tables.get(target_type)
    if not table:
        return False
    return connection.execute(
        f"SELECT 1 FROM {table} WHERE id=?", (target_id,)
    ).fetchone() is not None


def list_company_content_comments(connection, target_type, target_id=None):
    sql = "SELECT * FROM company_content_comments WHERE target_type=?"
    params = [target_type]
    if target_id is not None:
        sql += " AND target_id=?"
        params.append(target_id)
    sql += " ORDER BY target_id, created_at, id"
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def get_company_content_comment(connection, comment_id):
    row = connection.execute(
        "SELECT * FROM company_content_comments WHERE id=?", (comment_id,)
    ).fetchone()
    return dict(row) if row else None


def create_company_content_comment(
    connection, target_type, target_id, author_id, author_username, content,
    parent_id=None,
):
    text = (content or "").strip()
    if not text or len(text) > 1000:
        raise ValueError("댓글은 1~1,000자로 입력해주세요.")
    if not _company_comment_target_exists(connection, target_type, target_id):
        raise ValueError("댓글을 작성할 항목을 찾을 수 없습니다.")
    if parent_id is not None:
        parent = get_company_content_comment(connection, parent_id)
        if (
            not parent or parent["is_deleted"] or parent["parent_id"] is not None
            or parent["target_type"] != target_type
            or int(parent["target_id"]) != int(target_id)
        ):
            raise ValueError("답글을 작성할 댓글을 찾을 수 없습니다.")
    now = now_kst()
    ten_minutes_ago = (now - timedelta(minutes=10)).isoformat(timespec="seconds")
    day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
    recent_count = connection.execute(
        """SELECT COUNT(*) FROM company_content_comments
           WHERE author_id=? AND is_deleted=0 AND created_at>=?""",
        (author_id, ten_minutes_ago),
    ).fetchone()[0]
    daily_count = connection.execute(
        """SELECT COUNT(*) FROM company_content_comments
           WHERE author_id=? AND is_deleted=0 AND created_at>=?""",
        (author_id, day_ago),
    ).fetchone()[0]
    if recent_count >= 10 or daily_count >= 100:
        raise ValueError("댓글 작성 횟수가 너무 많습니다. 잠시 후 다시 시도해주세요.")
    timestamp = now.isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO company_content_comments (
            target_type, target_id, parent_id, author_id, author_username,
            content, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target_type, target_id, parent_id, author_id,
            (author_username or "")[:100], text, timestamp, timestamp,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def soft_delete_company_content_comment(connection, comment_id, user_id):
    timestamp = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """UPDATE company_content_comments
           SET is_deleted=1, deleted_at=?, deleted_by=?, updated_at=?
           WHERE id=? AND is_deleted=0""",
        (timestamp, user_id, timestamp, comment_id),
    )
    if not cursor.rowcount:
        raise ValueError("댓글을 찾을 수 없습니다.")
    connection.commit()


def list_latest_company_financial_reports(connection, company_name):
    """회사·제표별 가장 최근에 반영된 원본 보고서 메타데이터를 반환한다."""

    rows = connection.execute(
        """
        SELECT report.*
        FROM company_financial_reports AS report
        WHERE report.company_name = ?
          AND NOT EXISTS (
              SELECT 1
              FROM company_financial_reports AS newer
              WHERE newer.company_name = report.company_name
                AND newer.statement_type = report.statement_type
                AND (
                    COALESCE(newer.report_as_of, '') > COALESCE(report.report_as_of, '')
                    OR (
                        COALESCE(newer.report_as_of, '') = COALESCE(report.report_as_of, '')
                        AND newer.id > report.id
                    )
                )
          )
        ORDER BY CASE report.statement_type
                     WHEN 'income_statement' THEN 1
                     WHEN 'balance_sheet' THEN 2
                     WHEN 'cash_flow' THEN 3
                     ELSE 9
                 END,
                 report.id
        """,
        (company_name,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_company_financial_periods(connection, report_id, limit=5):
    rows = connection.execute(
        """
        SELECT DISTINCT fiscal_date
        FROM company_financial_values
        WHERE report_id = ?
        ORDER BY fiscal_date DESC
        LIMIT ?
        """,
        (report_id, max(1, int(limit))),
    ).fetchall()
    return [row["fiscal_date"] for row in rows]


def list_company_financial_statement_rows(connection, report_id, fiscal_dates):
    """화면용 최상위 계정과 선택 결산기의 원 단위 금액을 반환한다."""

    periods = [str(value) for value in fiscal_dates if value]
    if not periods:
        return []
    placeholders = ", ".join("?" for _ in periods)
    rows = connection.execute(
        f"""
        SELECT account_code, account_name, account_depth, display_order,
               fiscal_date, amount
        FROM company_financial_values
        WHERE report_id = ?
          AND account_depth = 0
          AND fiscal_date IN ({placeholders})
        ORDER BY display_order, fiscal_date
        """,
        (report_id, *periods),
    ).fetchall()
    return [dict(row) for row in rows]


def list_company_financial_values_for_reports(connection, report_ids):
    """Load top-level financial values for several reports in one query."""
    normalized_ids = list(dict.fromkeys(
        int(report_id) for report_id in report_ids if report_id
    ))
    if not normalized_ids:
        return []
    placeholders = ",".join("?" for _ in normalized_ids)
    rows = connection.execute(
        f"""
        SELECT report_id, account_code, account_name, account_depth,
               display_order, fiscal_date, amount
        FROM company_financial_values
        WHERE report_id IN ({placeholders})
          AND account_depth = 0
        ORDER BY report_id, display_order, fiscal_date
        """,
        normalized_ids,
    ).fetchall()
    return [dict(row) for row in rows]


def list_casino_market_share_financials(connection, start_year, end_year):
    """Return annual revenue and operating profit from each latest report."""
    rows = connection.execute(
        """
        SELECT report.company_name, value.account_code,
               value.fiscal_date, value.amount
        FROM company_financial_reports AS report
        JOIN company_financial_values AS value ON value.report_id = report.id
        WHERE report.statement_type = 'income_statement'
          AND value.account_code IN ('121000', '125000')
          AND value.period_type = 'annual'
          AND CAST(SUBSTR(value.fiscal_date, 1, 4) AS INTEGER) BETWEEN ? AND ?
          AND report.id = (
              SELECT newer.id
              FROM company_financial_reports AS newer
              WHERE newer.company_name = report.company_name
                AND newer.statement_type = report.statement_type
              ORDER BY newer.imported_at DESC, newer.id DESC
              LIMIT 1
          )
        ORDER BY value.fiscal_date, report.company_name, value.account_code
        """,
        (int(start_year), int(end_year)),
    ).fetchall()
    return [dict(row) for row in rows]


def get_latest_company_credit_rating(connection, company_name):
    row = connection.execute(
        """
        SELECT *
        FROM company_credit_ratings
        WHERE company_name = ?
        ORDER BY evaluated_on DESC, id DESC
        LIMIT 1
        """,
        (company_name,),
    ).fetchone()
    return dict(row) if row else None


def list_company_credit_ratings(connection, company_name, limit=None):
    sql = (
        "SELECT * FROM company_credit_ratings WHERE company_name = ? "
        "ORDER BY evaluated_on DESC, id DESC"
    )
    params = [company_name]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


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
        "document_type", "company_name", "title", "publisher", "report_date", "original_filename",
        "stored_filename", "mime_type", "file_size", "sha256", "page_count",
        "extracted_text", "extraction_status", "uploaded_by", "created_at", "updated_at",
    )
    values = [fields.get(column) for column in columns]
    values[0] = fields.get("document_type") or "research"
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


def get_research_document(connection, document_id, document_type="research"):
    row = connection.execute(
        """
        SELECT d.*, (
            SELECT GROUP_CONCAT(company_name, char(31))
            FROM research_document_companies rc WHERE rc.document_id=d.id
        ) AS company_names_csv
        FROM research_documents d WHERE d.id = ? AND d.document_type = ?
        """,
        (document_id, document_type),
    ).fetchone()
    return _decode_research_document(row)


def find_research_document_by_hash(
    connection, company_name, sha256, document_type=None
):
    sql = "SELECT * FROM research_documents WHERE company_name = ? AND sha256 = ?"
    params = [company_name, sha256]
    if document_type:
        sql += " AND document_type = ?"
        params.append(document_type)
    row = connection.execute(sql, params).fetchone()
    return _decode_research_document(row)


def list_research_documents(
    connection, company_name=None, limit=200, document_type="research"
):
    where = "WHERE d.document_type = ?"
    params = [document_type]
    if company_name:
        where += """
        AND EXISTS (
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


def update_research_document_analysis(
    connection,
    document_id,
    analysis=None,
    error_message=None,
    document_type="research",
):
    analysis = analysis or {}
    now_iso = now_kst().isoformat()
    connection.execute(
        """
        UPDATE research_documents
        SET ai_summary = ?, investment_stance = ?, target_price = ?,
            key_points_json = ?, risks_json = ?, analyzed_at = ?,
            error_message = ?, ai_suggested_title = ?, industry_impact = ?,
            updated_at = ?
        WHERE id = ? AND document_type = ?
        """,
        (
            analysis.get("ai_summary"),
            analysis.get("investment_stance"),
            analysis.get("target_price"),
            json.dumps(analysis.get("key_points") or [], ensure_ascii=False),
            json.dumps(analysis.get("risks") or [], ensure_ascii=False),
            now_iso if analysis else None,
            error_message,
            (analysis.get("suggested_title") or "").strip()[:200] or None,
            analysis.get("industry_impact"),
            now_iso,
            document_id,
            document_type,
        ),
    )
    connection.commit()


def update_research_document_title(
    connection, document_id, title, document_type="research"
):
    now_iso = now_kst().isoformat()
    cursor = connection.execute(
        """
        UPDATE research_documents
        SET title=?, updated_at=?
        WHERE id=? AND document_type=?
        """,
        (title, now_iso, document_id, document_type),
    )
    connection.commit()
    return cursor.rowcount > 0


def delete_research_document(connection, document_id, document_type="research"):
    connection.execute(
        "DELETE FROM research_documents WHERE id = ? AND document_type = ?",
        (document_id, document_type),
    )
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
        WHERE d.document_type = 'research'
          AND d.created_at >= datetime('now', ?)
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


def list_recent_disclosures(connection, days=7, important_only=False,
                            company_name=None, dart_corp_code=None):
    query = (
        "SELECT * FROM dart_disclosures WHERE "
        "date(substr(rcept_dt, 1, 4) || '-' || substr(rcept_dt, 5, 2) || '-' || substr(rcept_dt, 7, 2)) "
        ">= date('now', ?)"
    )
    params = [f"-{max(1, int(days))} days"]
    if important_only:
        query += " AND is_important = 1"
    if dart_corp_code:
        query += " AND (dart_corp_code = ? OR corp_name LIKE ?)"
        params.extend([dart_corp_code, f"%{company_name or ''}%"])
    elif company_name:
        query += " AND corp_name LIKE ?"
        params.append(f"%{company_name}%")
    query += " ORDER BY rcept_dt DESC"
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def list_disclosures_for_company(connection, company_name, dart_corp_code=None, days=90):
    clauses = [
        "date(substr(rcept_dt, 1, 4) || '-' || substr(rcept_dt, 5, 2) || '-' || substr(rcept_dt, 7, 2)) >= date('now', ?)"
    ]
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


def list_latest_disclosure_analyses(connection, disclosure_ids):
    """Return the latest analysis for each disclosure with bounded batch queries."""
    normalized_ids = list(dict.fromkeys(
        int(disclosure_id) for disclosure_id in disclosure_ids if disclosure_id
    ))
    results = {}
    for start in range(0, len(normalized_ids), 500):
        batch = normalized_ids[start:start + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            f"""
            SELECT analysis.*
            FROM disclosure_analysis AS analysis
            JOIN (
                SELECT disclosure_id, MAX(id) AS latest_id
                FROM disclosure_analysis
                WHERE disclosure_id IN ({placeholders})
                GROUP BY disclosure_id
            ) AS latest ON latest.latest_id = analysis.id
            """,
            batch,
        ).fetchall()
        results.update({row["disclosure_id"]: dict(row) for row in rows})
    return results


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


def upsert_government_legislative_notice(connection, notice):
    existing = connection.execute(
        "SELECT id FROM government_legislative_notices WHERE notice_id=?",
        (notice["notice_id"],),
    ).fetchone()
    now = now_kst().isoformat()
    connection.execute(
        """
        INSERT INTO government_legislative_notices (
            notice_id, notice_name, law_type, ministry_name, announcement_no,
            announcement_date, start_date, end_date, attachment_name,
            attachment_url, detail_url, view_count, announcement_type,
            matched_keyword, first_seen_at, last_checked_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(notice_id) DO UPDATE SET
            notice_name=excluded.notice_name,
            law_type=excluded.law_type,
            ministry_name=excluded.ministry_name,
            announcement_no=excluded.announcement_no,
            announcement_date=excluded.announcement_date,
            start_date=excluded.start_date,
            end_date=excluded.end_date,
            attachment_name=excluded.attachment_name,
            attachment_url=excluded.attachment_url,
            detail_url=excluded.detail_url,
            view_count=excluded.view_count,
            announcement_type=excluded.announcement_type,
            matched_keyword=excluded.matched_keyword,
            last_checked_at=excluded.last_checked_at,
            updated_at=excluded.updated_at
        """,
        (
            notice["notice_id"], notice["notice_name"], notice.get("law_type"),
            notice.get("ministry_name"), notice.get("announcement_no"),
            notice.get("announcement_date"), notice.get("start_date"),
            notice.get("end_date"), notice.get("attachment_name"),
            notice.get("attachment_url"), notice.get("detail_url"),
            notice.get("view_count"), notice.get("announcement_type"),
            notice.get("matched_keyword"), now, now, now,
        ),
    )
    connection.commit()
    return existing is None


def list_government_legislative_notices(connection, limit=50):
    rows = connection.execute(
        """
        SELECT *,
               CASE
                 WHEN end_date IS NOT NULL AND replace(end_date, '.', '-') >= date('now')
                 THEN 1 ELSE 0
               END AS is_open
        FROM government_legislative_notices
        ORDER BY is_open DESC, COALESCE(announcement_date, '') DESC, id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_market_quote(connection, quote):
    connection.execute(
        """
        INSERT INTO market_quotes (
            symbol, name, asset_type, market, base_date, close_price,
            change_value, change_rate, open_price, high_price, low_price,
            volume, market_cap, fetched_at, currency, source, fetch_status,
            fetch_error, last_attempt_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', NULL, ?)
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
            market_cap = COALESCE(excluded.market_cap, market_quotes.market_cap),
            fetched_at = excluded.fetched_at,
            currency = excluded.currency,
            source = excluded.source,
            fetch_status = 'success',
            fetch_error = NULL,
            last_attempt_at = excluded.last_attempt_at
        """,
        (
            quote["symbol"], quote["name"], quote["asset_type"],
            quote.get("market"), quote.get("base_date"), quote.get("close_price"),
            quote.get("change_value"), quote.get("change_rate"),
            quote.get("open_price"), quote.get("high_price"), quote.get("low_price"),
            quote.get("volume"), quote.get("market_cap"), now_kst().isoformat(),
            quote.get("currency"), quote.get("source"), now_kst().isoformat(),
        ),
    )
    date_text = str(quote.get("base_date") or now_kst().date().isoformat()).replace(".", "-")
    if len(date_text) == 8 and date_text.isdigit():
        date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
    symbol = str(quote["symbol"])
    market_fields = {
        "close_price": ("종가", quote.get("currency") or "KRW", "last"),
        "change_value": ("전일 대비", quote.get("currency") or "KRW", "last"),
        "change_rate": ("등락률", "%", "last"),
        "open_price": ("시가", quote.get("currency") or "KRW", "last"),
        "high_price": ("고가", quote.get("currency") or "KRW", "last"),
        "low_price": ("저가", quote.get("currency") or "KRW", "last"),
        "volume": ("거래량", "주", "sum"),
        "market_cap": ("시가총액", quote.get("currency") or "KRW", "last"),
    }
    for field, (metric_label, unit, aggregation) in market_fields.items():
        value = quote.get(field)
        if value is None:
            continue
        key = f"market.{symbol}.{field}"
        upsert_source_data_series(
            connection, series_key=key, category="주가", label=f"{quote['name']} {metric_label}",
            unit=unit, frequency="daily", aggregation=aggregation,
            source_name=quote.get("source") or "공공데이터·글로벌 시세",
        )
        upsert_source_data_point(
            connection, series_key=key, observation_date=date_text[:10], value=value,
            source_record_key=f"{symbol}:{date_text[:10]}",
        )
    connection.commit()


def mark_market_quote_failure(connection, symbol, error):
    """마지막 정상 시세는 유지하고 조회 상태만 실패로 바꾼다."""
    connection.execute(
        """
        UPDATE market_quotes
        SET fetch_status='failed', fetch_error=?, last_attempt_at=?
        WHERE symbol=?
        """,
        (str(error)[:500], now_kst().isoformat(), symbol),
    )
    connection.commit()


def global_market_quotes_need_refresh(connection, max_age_minutes=10):
    symbols = ("1928.HK", "0027.HK", "0880.HK", "MLCO")
    placeholders = ",".join("?" for _ in symbols)
    row = connection.execute(
        f"""
        SELECT COUNT(*) AS quote_count, MIN(last_attempt_at) AS oldest_attempt
        FROM market_quotes WHERE symbol IN ({placeholders})
        """,
        symbols,
    ).fetchone()
    if not row or row["quote_count"] < len(symbols) or not row["oldest_attempt"]:
        return True
    try:
        attempted = datetime.fromisoformat(row["oldest_attempt"])
        return now_kst() - attempted >= timedelta(minutes=max_age_minutes)
    except (TypeError, ValueError):
        return True


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
    row = connection.execute(
        "SELECT name, currency, source FROM market_quotes WHERE symbol=?", (symbol,)
    ).fetchone()
    name = row["name"] if row else symbol
    unit = (row["currency"] if row else None) or "KRW"
    source = (row["source"] if row else None) or "공공데이터·글로벌 시세"
    key = f"market.{symbol}.close_price"
    upsert_source_data_series(
        connection, series_key=key, category="주가", label=f"{name} 종가",
        unit=unit, frequency="daily", aggregation="last", source_name=source,
    )
    for point in points:
        if point.get("base_date") and point.get("close_price") is not None:
            date_text = str(point["base_date"])
            if len(date_text) == 8 and date_text.isdigit():
                date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
            upsert_source_data_point(
                connection, series_key=key, observation_date=date_text[:10],
                value=point["close_price"], source_record_key=f"{symbol}:{date_text[:10]}",
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
    order = {
        "KOSPI": 0, "034230": 1, "114090": 2, "035250": 3, "032350": 4,
        "1928.HK": 10, "0027.HK": 11, "0880.HK": 12, "MLCO": 13,
    }
    rows = [dict(row) for row in connection.execute("SELECT * FROM market_quotes").fetchall()]
    exchange_rates = {}
    for currency, code in (("USD", "FX_USD"), ("HKD", "FX_HKD")):
        rate = connection.execute(
            "SELECT value, observation_date FROM economic_series WHERE series_code=? "
            "ORDER BY observation_date DESC LIMIT 1",
            (code,),
        ).fetchone()
        if rate:
            exchange_rates[currency] = dict(rate)
    for row in rows:
        row.update(_market_sparkline(connection, row["symbol"]))
        market_cap = row.get("market_cap")
        if market_cap and row.get("asset_type") == "global_stock":
            currency = row.get("currency") or ""
            value = float(market_cap)
            if value >= 1_000_000_000_000:
                row["market_cap_label"] = f"{currency} {value / 1_000_000_000_000:,.2f}T"
            elif value >= 1_000_000_000:
                row["market_cap_label"] = f"{currency} {value / 1_000_000_000:,.2f}B"
            else:
                row["market_cap_label"] = f"{currency} {value / 1_000_000:,.2f}M"
        elif market_cap:
            trillion, remainder = divmod(int(market_cap), 1_000_000_000_000)
            hundred_million = remainder // 100_000_000
            row["market_cap_label"] = f"{trillion}조 {hundred_million:,}억원" if trillion else f"{hundred_million:,}억원"
        else:
            row["market_cap_label"] = None
        rate = exchange_rates.get(row.get("currency"))
        if row.get("asset_type") == "global_stock" and rate and row.get("close_price") is not None:
            row["krw_estimate"] = round(float(row["close_price"]) * float(rate["value"]))
            row["krw_rate_date"] = rate["observation_date"]
        else:
            row["krw_estimate"] = None
            row["krw_rate_date"] = None
        if row.get("asset_type") == "global_stock" and rate and market_cap:
            won = round(float(market_cap) * float(rate["value"]))
            trillion, remainder = divmod(won, 1_000_000_000_000)
            hundred_million = remainder // 100_000_000
            row["market_cap_krw_label"] = (
                f"{trillion:,}조 {hundred_million:,}억원" if trillion and hundred_million
                else (f"{trillion:,}조원" if trillion else f"{hundred_million:,}억원")
            )
        else:
            row["market_cap_krw_label"] = None
    return sorted(rows, key=lambda row: order.get(row["symbol"], 99))


def upsert_salary_snapshot(connection, item):
    connection.execute(
        """
        INSERT INTO salary_snapshots (
            entity_code, entity_name, entity_type, average_salary_manwon,
            source_name, source_url, source_period, collected_date, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_code, collected_date) DO UPDATE SET
            entity_name=excluded.entity_name,
            entity_type=excluded.entity_type,
            average_salary_manwon=excluded.average_salary_manwon,
            source_name=excluded.source_name,
            source_url=excluded.source_url,
            source_period=excluded.source_period,
            fetched_at=excluded.fetched_at
        """,
        (
            item["entity_code"], item["entity_name"], item["entity_type"],
            item["average_salary_manwon"], item["source_name"],
            item.get("source_url"), item.get("source_period"),
            item["collected_date"], item["fetched_at"],
        ),
    )
    key = f"salary.{item['entity_code']}.average"
    upsert_source_data_series(
        connection, series_key=key, category="연봉", label=f"{item['entity_name']} 평균 연봉",
        unit="만원", frequency="monthly", aggregation="last",
        source_name=item["source_name"], source_url=item.get("source_url"),
    )
    upsert_source_data_point(
        connection, series_key=key, observation_date=item["collected_date"][:10],
        value=item["average_salary_manwon"],
        source_record_key=f"{item['entity_code']}:{item['collected_date']}",
    )
    connection.commit()


def upsert_employer_review_snapshot(connection, item):
    connection.execute(
        """
        INSERT INTO employer_review_snapshots (
            entity_code, entity_name, source_code, source_name, rating,
            review_count, source_url, collected_date, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_code, source_code, collected_date) DO UPDATE SET
            entity_name=excluded.entity_name,
            source_name=excluded.source_name,
            rating=excluded.rating,
            review_count=excluded.review_count,
            source_url=excluded.source_url,
            fetched_at=excluded.fetched_at
        """,
        (
            item["entity_code"], item["entity_name"], item["source_code"],
            item["source_name"], item["rating"], item.get("review_count"),
            item["source_url"], item["collected_date"], item["fetched_at"],
        ),
    )
    key = f"employer_rating.{item['entity_code']}.{item['source_code']}"
    upsert_source_data_series(
        connection,
        series_key=key,
        category="연봉·평점",
        label=f"{item['entity_name']} {item['source_name']} 평점",
        unit="점",
        frequency="daily",
        aggregation="last",
        source_name=item["source_name"],
        source_url=item["source_url"],
    )
    upsert_source_data_point(
        connection,
        series_key=key,
        observation_date=item["collected_date"][:10],
        value=item["rating"],
        source_record_key=(
            f"{item['entity_code']}:{item['source_code']}:{item['collected_date']}"
        ),
    )
    connection.commit()


def list_salary_dashboard(connection):
    latest_rows = connection.execute(
        """
        SELECT s.* FROM salary_snapshots s
        JOIN (
            SELECT entity_code, MAX(collected_date) AS latest_date
            FROM salary_snapshots GROUP BY entity_code
        ) latest ON latest.entity_code=s.entity_code
                AND latest.latest_date=s.collected_date
        """
    ).fetchall()
    order = {
        "paradise": 0, "gkl": 1, "kangwon_land": 2, "lotte_tour": 3,
        "casino_average": 10, "hotel_average": 11,
    }
    items = sorted((dict(row) for row in latest_rows),
                   key=lambda row: order.get(row["entity_code"], 99))
    latest_reviews = connection.execute(
        """
        SELECT r.* FROM employer_review_snapshots r
        JOIN (
            SELECT entity_code, source_code, MAX(collected_date) AS latest_date
            FROM employer_review_snapshots GROUP BY entity_code, source_code
        ) latest ON latest.entity_code=r.entity_code
                AND latest.source_code=r.source_code
                AND latest.latest_date=r.collected_date
        ORDER BY r.source_name
        """
    ).fetchall()
    reviews_by_entity = {}
    for review in latest_reviews:
        reviews_by_entity.setdefault(review["entity_code"], []).append(dict(review))
    salary_entity_codes = {item["entity_code"] for item in items}
    for entity_code, reviews in reviews_by_entity.items():
        if entity_code in salary_entity_codes:
            continue
        items.append({
            "entity_code": entity_code,
            "entity_name": reviews[0]["entity_name"],
            "entity_type": "company",
            "average_salary_manwon": None,
            "source_name": None,
            "source_url": None,
            "source_period": None,
            "collected_date": None,
            "fetched_at": reviews[0]["fetched_at"],
        })
    for item in items:
        item["review_ratings"] = reviews_by_entity.get(item["entity_code"], [])
        monthly = connection.execute(
            """
            SELECT s.collected_date, s.average_salary_manwon
            FROM salary_snapshots s
            JOIN (
                SELECT SUBSTR(collected_date, 1, 7) AS ym, MAX(collected_date) AS max_date
                FROM salary_snapshots WHERE entity_code=?
                GROUP BY SUBSTR(collected_date, 1, 7)
            ) m ON m.max_date=s.collected_date
            WHERE s.entity_code=? ORDER BY s.collected_date DESC LIMIT 12
            """,
            (item["entity_code"], item["entity_code"]),
        ).fetchall()
        item["monthly_history"] = list(reversed([dict(row) for row in monthly]))
        history = item["monthly_history"]
        if len(history) >= 2:
            values = [row["average_salary_manwon"] for row in history]
            low, high = min(values), max(values)
            spread = high - low or 1
            points = [
                f"{index / (len(values) - 1) * 100:.1f},"
                f"{34 - (value - low) / spread * 27:.1f}"
                for index, value in enumerate(values)
            ]
            item["trend_points"] = " ".join(points)
            item["trend_area_points"] = f"0,40 {' '.join(points)} 100,40"
            item["monthly_change"] = values[-1] - values[-2]
        else:
            item["trend_points"] = ""
            item["trend_area_points"] = ""
            item["monthly_change"] = None
    return items


def upsert_recruitment_job(connection, item):
    connection.execute(
        """
        INSERT INTO recruitment_jobs (
            source_name, source_job_id, company_name, title, employment_type,
            location, deadline, compensation_summary, benefits_summary,
            ai_summary, treatment_level, source_url, raw_text, posted_at,
            first_seen_at, last_seen_at, analyzed_at, analysis_error, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(source_name, source_job_id) DO UPDATE SET
            company_name=excluded.company_name, title=excluded.title,
            employment_type=excluded.employment_type, location=excluded.location,
            deadline=excluded.deadline,
            compensation_summary=excluded.compensation_summary,
            benefits_summary=excluded.benefits_summary,
            ai_summary=COALESCE(excluded.ai_summary, recruitment_jobs.ai_summary),
            treatment_level=COALESCE(excluded.treatment_level, recruitment_jobs.treatment_level),
            source_url=excluded.source_url, raw_text=excluded.raw_text,
            posted_at=excluded.posted_at, last_seen_at=excluded.last_seen_at,
            analyzed_at=COALESCE(excluded.analyzed_at, recruitment_jobs.analyzed_at),
            analysis_error=excluded.analysis_error, is_active=1
        """,
        (
            item["source_name"], item["source_job_id"], item.get("company_name"),
            item["title"], item.get("employment_type"), item.get("location"),
            item.get("deadline"), item.get("compensation_summary"),
            item.get("benefits_summary"), item.get("ai_summary"),
            item.get("treatment_level"), item["source_url"], item.get("raw_text"),
            item.get("posted_at"), item["first_seen_at"], item["last_seen_at"],
            item.get("analyzed_at"), item.get("analysis_error"),
        ),
    )
    observation_date = str(item["last_seen_at"])[:10]
    active_count = connection.execute(
        "SELECT COUNT(*) AS c FROM recruitment_jobs WHERE is_active=1"
    ).fetchone()["c"]
    upsert_source_data_series(
        connection, series_key="recruitment.active_jobs", category="채용",
        label="활성 채용공고", unit="건", frequency="daily", aggregation="last",
        source_name="채용 사이트 수집",
    )
    upsert_source_data_point(
        connection, series_key="recruitment.active_jobs",
        observation_date=observation_date, value=active_count,
        source_record_key=f"active:{observation_date}",
    )
    connection.commit()


def list_recruitment_jobs(connection, term="", source="", employment_type="", limit=200):
    conditions = ["is_active=1"]
    params = []
    if term:
        like = f"%{term}%"
        conditions.append(
            "(title LIKE ? OR company_name LIKE ? OR raw_text LIKE ? OR ai_summary LIKE ?)"
        )
        params.extend([like] * 4)
    if source:
        conditions.append("source_name=?")
        params.append(source)
    if employment_type:
        conditions.append("employment_type=?")
        params.append(employment_type)
    params.append(max(1, int(limit)))
    rows = connection.execute(
        f"SELECT * FROM recruitment_jobs WHERE {' AND '.join(conditions)} "
        "ORDER BY COALESCE(posted_at, first_seen_at) DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def search_recruitment_jobs(connection, term, days=365, limit=100):
    since = (now_kst() - timedelta(days=max(1, int(days)))).isoformat()
    like = f"%{term}%"
    rows = connection.execute(
        """
        SELECT * FROM recruitment_jobs
        WHERE is_active=1 AND last_seen_at>=?
          AND (title LIKE ? OR company_name LIKE ? OR raw_text LIKE ? OR ai_summary LIKE ?)
        ORDER BY last_seen_at DESC LIMIT ?
        """,
        (since, like, like, like, like, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


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
    date_text = str(item["observation_date"])
    if len(date_text) == 8 and date_text.isdigit():
        date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
    key = f"economy.{item['series_code']}"
    upsert_source_data_series(
        connection, series_key=key, category="유가·환율", label=item["label"],
        unit=item["unit"], frequency="daily", aggregation="last",
        source_name=item["source"],
    )
    upsert_source_data_point(
        connection, series_key=key, observation_date=date_text[:10],
        value=item["value"], source_record_key=f"{item['series_code']}:{date_text[:10]}",
    )
    connection.commit()


# ============================================================
# source_data_repository
# ============================================================

def upsert_source_data_series(
    connection, *, series_key, category, label, unit, frequency,
    aggregation="sum", source_name="CASINO IN", source_url=None,
    is_internal=False, commit=False,
):
    """통합 숫자 저장소의 데이터 종류를 멱등 등록한다."""
    now = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO source_data_series (
            series_key, category, label, unit, frequency, aggregation,
            source_name, source_url, is_internal, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(series_key) DO UPDATE SET
            category=excluded.category, label=excluded.label, unit=excluded.unit,
            frequency=excluded.frequency, aggregation=excluded.aggregation,
            source_name=excluded.source_name, source_url=excluded.source_url,
            is_internal=excluded.is_internal, is_active=1, updated_at=excluded.updated_at
        """,
        (
            series_key, category, label, unit, frequency, aggregation,
            source_name, source_url, 1 if is_internal else 0, now, now,
        ),
    )
    if commit:
        connection.commit()


def upsert_source_data_point(
    connection, *, series_key, observation_date, value,
    source_record_key=None, commit=False,
):
    """같은 데이터 종류·관측일은 갱신하고 새로운 날짜는 계속 누적한다."""
    if value is None:
        return
    now = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO source_data_points (
            series_key, observation_date, value, source_record_key,
            recorded_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(series_key, observation_date) DO UPDATE SET
            value=excluded.value,
            source_record_key=COALESCE(excluded.source_record_key, source_data_points.source_record_key),
            updated_at=excluded.updated_at
        """,
        (series_key, observation_date, float(value), source_record_key, now, now),
    )
    if commit:
        connection.commit()


def list_source_data_series(connection, include_internal=False):
    conditions = ["is_active=1"]
    if not include_internal:
        conditions.append("is_internal=0")
    rows = connection.execute(
        f"SELECT * FROM source_data_series WHERE {' AND '.join(conditions)} "
        "ORDER BY category, label, series_key"
    ).fetchall()
    return [dict(row) for row in rows]


def list_source_data_points(connection, series_keys, start_date, end_date, include_internal=False):
    if not series_keys:
        return []
    placeholders = ",".join("?" for _ in series_keys)
    internal_clause = "" if include_internal else " AND s.is_internal=0"
    rows = connection.execute(
        f"""
        SELECT p.series_key, p.observation_date, p.value, p.updated_at
        FROM source_data_points p
        JOIN source_data_series s ON s.series_key=p.series_key
        WHERE p.series_key IN ({placeholders})
          AND p.observation_date BETWEEN ? AND ?
          AND s.is_active=1{internal_clause}
        ORDER BY p.series_key, p.observation_date
        """,
        [*series_keys, start_date, end_date],
    ).fetchall()
    return [dict(row) for row in rows]


def get_source_data_repository_state(connection, state_key):
    row = connection.execute(
        "SELECT state_value, updated_at FROM source_data_repository_state WHERE state_key=?",
        (state_key,),
    ).fetchone()
    return dict(row) if row else None


def set_source_data_repository_state(connection, state_key, state_value, commit=False):
    now = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO source_data_repository_state (state_key, state_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            state_value=excluded.state_value, updated_at=excluded.updated_at
        """,
        (state_key, str(state_value), now),
    )
    if commit:
        connection.commit()


def source_data_repository_stats(connection, include_internal=False):
    internal_clause = "" if include_internal else "WHERE s.is_internal=0"
    row = connection.execute(
        f"""
        SELECT COUNT(DISTINCT s.series_key) AS series_count,
               COUNT(p.id) AS point_count,
               MIN(p.observation_date) AS first_date,
               MAX(p.observation_date) AS last_date,
               MAX(p.updated_at) AS updated_at
        FROM source_data_series s
        LEFT JOIN source_data_points p ON p.series_key=s.series_key
        {internal_clause}
        """
    ).fetchone()
    return dict(row) if row else {}


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
    order = ("OIL_B027", "OIL_D047", "OIL_K015", "FX_USD", "FX_HKD", "FX_JPY100", "FX_CNH", "FX_EUR")
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

def record_api_usage(
    connection, model, request_type, input_tokens, output_tokens, estimated_cost,
    success, request_summary=None, response_summary=None, error_message=None,
):
    connection.execute(
        """
        INSERT INTO api_usage (
            called_at, model, request_type, input_tokens, output_tokens,
            estimated_cost, success, provider, request_summary, response_summary,
            error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'openai', ?, ?, ?)
        """,
        (
            now_kst().isoformat(), model, request_type, input_tokens, output_tokens,
            estimated_cost, 1 if success else 0,
            str(request_summary or "")[:4000] or None,
            str(response_summary or "")[:8000] or None,
            str(error_message or "")[:2000] or None,
        ),
    )
    connection.commit()


def get_today_usage_summary(connection):
    now = now_kst()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    reset_row = connection.execute(
        "SELECT setting_value FROM site_settings WHERE setting_key='openai_usage_reset_at'"
    ).fetchone()
    reset_at = reset_row["setting_value"] if reset_row else ""
    since = reset_at if reset_at.startswith(now.strftime("%Y-%m-%d")) else today_start
    row = connection.execute(
        "SELECT COUNT(*) AS call_count, COALESCE(SUM(estimated_cost), 0) AS total_cost "
        "FROM api_usage WHERE called_at>=? AND (provider='openai' OR provider IS NULL)",
        (since,),
    ).fetchone()
    return {"call_count": row["call_count"], "total_cost": row["total_cost"]}


def purge_logs_older_than(connection, days=30):
    days = max(1, min(int(days), 3650))
    cutoff = (now_kst() - timedelta(days=days)).isoformat(timespec="seconds")
    deleted = {}
    for table, column in (
        ("security_audit_log", "created_at"),
        ("dashboard_user_audit", "created_at"),
        ("api_usage", "called_at"),
        ("errors", "occurred_at"),
        ("dashboard_analysis_runs", "started_at"),
        ("official_document_change_log", "created_at"),
        ("localization_events", "created_at"),
    ):
        cursor = connection.execute(
            f"DELETE FROM {table} WHERE {column} < ?", (cutoff,)
        )
        deleted[table] = cursor.rowcount
    alert_cutoff = (now_kst() - timedelta(days=days)).strftime("%Y-%m-%d")
    cursor = connection.execute(
        "DELETE FROM ai_limit_alerts WHERE alert_date < ?", (alert_cutoff,)
    )
    deleted["ai_limit_alerts"] = cursor.rowcount
    return deleted


def claim_ai_limit_alert(connection, limit_type, request_type, summary):
    now = now_kst()
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO ai_limit_alerts (
            alert_date, limit_type, request_type, call_count, total_cost, claimed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            now.strftime("%Y-%m-%d"),
            limit_type,
            request_type,
            summary["call_count"],
            summary["total_cost"],
            now.isoformat(),
        ),
    )
    connection.commit()
    return cursor.rowcount == 1


def mark_ai_limit_alert_sent(connection, limit_type):
    connection.execute(
        """
        UPDATE ai_limit_alerts SET sent_at=?
        WHERE alert_date=? AND limit_type=?
        """,
        (now_kst().isoformat(), now_kst().strftime("%Y-%m-%d"), limit_type),
    )
    connection.commit()


def release_ai_limit_alert(connection, limit_type):
    connection.execute(
        "DELETE FROM ai_limit_alerts WHERE alert_date=? AND limit_type=? AND sent_at IS NULL",
        (now_kst().strftime("%Y-%m-%d"), limit_type),
    )
    connection.commit()


def log_error(connection, stage, error_type, error_message):
    connection.execute(
        "INSERT INTO errors (occurred_at, stage, error_type, error_message) VALUES (?, ?, ?, ?)",
        (now_kst().isoformat(), stage, error_type, (error_message or "")[:2000]),
    )
    connection.commit()
