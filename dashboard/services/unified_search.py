"""검색이 허용된 사용자 콘텐츠만 단일 시간순 타임라인으로 변환한다."""

from datetime import datetime, timezone

from dashboard_db import queries
from services import news_reader

SOURCE_LABELS = {
    "news": "뉴스",
    "disclosure": "공시",
    "law": "법령",
    "research": "리서치",
    "recruitment": "채용",
    "community": "자유 게시판",
    "notice": "공지사항",
    "review": "리뷰",
    "archive": "아카이브",
    "work_note": "업무노트",
    "tips": "자료실",
}


def _sort_key(item):
    raw = item.get("occurred_at") or ""
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    except (TypeError, ValueError):
        return 0


def search(connection, term, days=365, sources=None, limit=200, user_id=None):
    term = (term or "").strip()
    if not term:
        return []
    enabled = set(sources or SOURCE_LABELS)
    items = []

    if "news" in enabled:
        for row in news_reader.search_articles(term, days=days, limit=limit):
            items.append({
                "source": "news", "source_label": SOURCE_LABELS["news"],
                "title": row.get("title") or row.get("issue_title") or "제목 없음",
                "summary": row.get("latest_summary") or row.get("category"),
                "occurred_at": row.get("published_at") or row.get("collected_at"),
                "meta": row.get("publisher"), "url": row.get("original_url"),
                "importance": row.get("importance") or row.get("importance_score"),
            })

    dashboard_sources = {
        "disclosure": queries.search_disclosures,
        "law": queries.search_law_updates,
        "research": queries.search_research_documents,
        "recruitment": queries.search_recruitment_jobs,
    }
    for source, search_func in dashboard_sources.items():
        if source not in enabled:
            continue
        for row in search_func(connection, term, days=days, limit=limit):
            items.append(_normalize_dashboard_item(source, row))

    like = f"%{term}%"
    community_sources = {
        "community": ("community", "community_board_page", "/board"),
        "notice": ("notice", "notice_board_page", "/board"),
        "review": ("review", "review_board_page", "/blog/reviews"),
        "archive": ("diary", "diary_board_page", "/board/diary"),
    }
    for source, (board_type, _endpoint, base_url) in community_sources.items():
        if source not in enabled:
            continue
        rows = connection.execute(
            """SELECT id,title,content,tags_json,author_username,created_at,diary_date
               FROM community_posts
               WHERE board_type=? AND is_deleted=0
                 AND (is_private=0 OR author_id=?)
                 AND (title LIKE ? OR content LIKE ? OR tags_json LIKE ?)
               ORDER BY created_at DESC,id DESC LIMIT ?""",
            (board_type, int(user_id or -1), like, like, like, max(1, min(int(limit), 250))),
        ).fetchall()
        for row in rows:
            path = (
                f"{base_url}/{row['id']}"
                if source in {"review", "archive"}
                else f"/board/posts/{row['id']}"
            )
            items.append({
                "source": source, "source_label": SOURCE_LABELS[source],
                "title": row["title"], "summary": (row["content"] or "")[:500],
                "occurred_at": row["diary_date"] or row["created_at"],
                "meta": row["author_username"], "url": path, "importance": None,
            })

    if "work_note" in enabled and user_id:
        rows = connection.execute(
            """SELECT id,title,content,tags_json,status,updated_at
               FROM work_notes
               WHERE author_id=? AND is_deleted=0
                 AND (title LIKE ? OR content LIKE ? OR tags_json LIKE ?)
               ORDER BY updated_at DESC,id DESC LIMIT ?""",
            (int(user_id), like, like, like, max(1, min(int(limit), 250))),
        ).fetchall()
        for row in rows:
            items.append({
                "source": "work_note", "source_label": SOURCE_LABELS["work_note"],
                "title": row["title"], "summary": (row["content"] or "")[:500],
                "occurred_at": row["updated_at"], "meta": row["status"],
                "url": f"/blog/work-notes/{row['id']}", "importance": None,
            })

    if "tips" in enabled:
        rows = connection.execute(
            """SELECT slug,title,summary,body,category,tags_json,updated_at
               FROM tips_articles
               WHERE is_deleted=0 AND draft=0
                 AND (title LIKE ? OR summary LIKE ? OR body LIKE ? OR tags_json LIKE ?)
               ORDER BY updated_at DESC LIMIT ?""",
            (like, like, like, like, max(1, min(int(limit), 250))),
        ).fetchall()
        for row in rows:
            items.append({
                "source": "tips", "source_label": SOURCE_LABELS["tips"],
                "title": row["title"], "summary": row["summary"] or (row["body"] or "")[:500],
                "occurred_at": row["updated_at"], "meta": row["category"],
                "url": f"/resources/{row['slug']}", "importance": None,
            })

    items.sort(key=_sort_key, reverse=True)
    return items[: max(1, int(limit))]


def _normalize_dashboard_item(source, row):
    if source == "recruitment":
        return {
            "source": source, "source_label": SOURCE_LABELS[source],
            "title": row.get("title") or "채용공고",
            "summary": row.get("ai_summary") or row.get("compensation_summary"),
            "occurred_at": row.get("posted_at") or row.get("first_seen_at"),
            "meta": " · ".join(filter(None, [
                row.get("company_name"), row.get("employment_type"),
                row.get("source_name"), row.get("deadline"),
            ])),
            "url": row.get("source_url"), "importance": row.get("treatment_level"),
        }
    if source == "research":
        return {
            "source": source, "source_label": SOURCE_LABELS[source],
            "title": row.get("title") or row.get("original_filename") or "업로드 자료",
            "summary": row.get("ai_summary") or (row.get("extracted_text") or "")[:500],
            "occurred_at": row.get("report_date") or row.get("created_at"),
            "meta": " · ".join(filter(None, [row.get("company_name"), row.get("publisher")])),
            "url": f"/companies/reports/{row['id']}/download", "importance": None,
        }
    if source == "disclosure":
        return {
            "source": source, "source_label": SOURCE_LABELS[source],
            "title": row.get("report_nm") or "공시",
            "summary": row.get("ai_summary") or row.get("financial_impact"),
            "occurred_at": row.get("rcept_dt") or row.get("fetched_at"),
            "meta": row.get("corp_name"), "url": row.get("dart_link"),
            "importance": row.get("importance") or ("high" if row.get("is_important") else None),
        }
    if source == "law":
        return {
            "source": source, "source_label": SOURCE_LABELS[source],
            "title": row.get("law_name") or "법령 변경",
            "summary": row.get("ai_summary") or row.get("company_impact") or row.get("action_needed"),
            "occurred_at": row.get("effective_date") or row.get("fetched_at"),
            "meta": row.get("status"), "url": None, "importance": None,
        }
    raise ValueError(f"허용되지 않은 검색 소스: {source}")
