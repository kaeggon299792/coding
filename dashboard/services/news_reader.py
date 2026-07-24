"""
casino_news_watch의 news_history.db를 읽기 전용으로 조회한다.

이 모듈은 news_history.db에 어떤 쓰기 작업도 하지 않는다(extensions.news_db_readonly()가
물리적으로 읽기 전용 연결만 제공). DB 파일에 접근할 수 없거나 쿼리가 실패해도
예외를 밖으로 던지지 않고 빈 결과를 반환해, 대시보드 전체가 중단되지 않도록 한다.

news_history.db 스키마(casino_news_watch/database.py 기준):
  articles(article_id, normalized_url, original_url, normalized_title, title,
           publisher, published_at, collected_at, content_hash, status,
           relevance_score, importance_score, issue_id, sent_at)
  issues(issue_id, issue_key, issue_title, category, first_seen_at, last_seen_at,
         importance, impact_direction, latest_summary, sent_at, updated_at,
         representative_normalized_title)
"""

import logging

from extensions import news_db_readonly
from utils import today_kst_str

logger = logging.getLogger("dashboard")


def _safe_query(query, params=()):
    """읽기 전용 연결로 쿼리를 실행한다. 연결/쿼리 실패 시 빈 리스트를 반환한다."""
    connection = news_db_readonly()
    if connection is None:
        logger.warning("news_history.db에 연결할 수 없습니다(경로 미설정 또는 파일 없음).")
        return []
    try:
        rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("news_history.db 조회 오류: %s", error)
        return []
    finally:
        connection.close()


def today_important_articles(min_importance_score=60):
    """오늘(KST) 수집되었고 이슈(issues)와 연결된 기사 중 중요도가 높은 것만 반환한다."""
    today = today_kst_str()
    return _safe_query(
        """
        SELECT
            articles.article_id, articles.title, articles.publisher,
            articles.original_url, articles.published_at, articles.collected_at,
            articles.importance_score, articles.relevance_score,
            issues.issue_key, issues.issue_title, issues.category,
            issues.importance, issues.impact_direction, issues.latest_summary,
            issues.first_seen_at
        FROM articles
        LEFT JOIN issues ON issues.issue_id = articles.issue_id
        WHERE articles.collected_at LIKE ?
          AND (articles.importance_score IS NULL OR articles.importance_score >= ?)
          AND articles.status IS NOT NULL
        ORDER BY articles.importance_score DESC, articles.collected_at DESC
        LIMIT 100
        """,
        (f"{today}%", min_importance_score),
    )


def count_today_articles():
    today = today_kst_str()
    rows = _safe_query(
        "SELECT COUNT(*) AS c FROM articles WHERE collected_at LIKE ?", (f"{today}%",)
    )
    return rows[0]["c"] if rows else 0


def count_today_important_articles(min_importance_score=60):
    today = today_kst_str()
    rows = _safe_query(
        "SELECT COUNT(*) AS c FROM articles WHERE collected_at LIKE ? AND importance_score >= ?",
        (f"{today}%", min_importance_score),
    )
    return rows[0]["c"] if rows else 0


def count_yesterday_important_articles(min_importance_score=60):
    rows = _safe_query(
        "SELECT COUNT(*) AS c FROM articles "
        "WHERE date(collected_at) = date('now', '-1 day') AND importance_score >= ?",
        (min_importance_score,),
    )
    return rows[0]["c"] if rows else 0


def count_new_issues_today_by_category(category_keywords):
    """오늘 처음 발견된(first_seen_at=오늘) 이슈 수를 카테고리 키워드로 필터링해 센다.

    category_keywords: issues.category 컬럼에 대해 부분일치할 키워드 리스트.
    """
    today = today_kst_str()
    if not category_keywords:
        rows = _safe_query(
            "SELECT COUNT(*) AS c FROM issues WHERE first_seen_at LIKE ?", (f"{today}%",)
        )
        return rows[0]["c"] if rows else 0

    placeholders = " OR ".join(["category LIKE ?"] * len(category_keywords))
    params = [f"{today}%"] + [f"%{kw}%" for kw in category_keywords]
    rows = _safe_query(
        f"SELECT COUNT(*) AS c FROM issues WHERE first_seen_at LIKE ? AND ({placeholders})",
        params,
    )
    return rows[0]["c"] if rows else 0


def recent_issues_by_category(category_keywords, days=7):
    if not category_keywords:
        return []
    placeholders = " OR ".join(["category LIKE ?"] * len(category_keywords))
    params = [f"-{days} days"] + [f"%{kw}%" for kw in category_keywords]
    return _safe_query(
        f"""
        SELECT * FROM issues
        WHERE last_seen_at >= datetime('now', ?) AND ({placeholders})
        ORDER BY last_seen_at DESC
        LIMIT 50
        """,
        params,
    )
