"""서로 다른 세 DB의 검색 결과를 단일 시간순 타임라인으로 변환한다."""

from datetime import datetime, timezone

from dashboard_db import queries
from services import news_reader

SOURCE_LABELS = {
    "news": "뉴스",
    "disclosure": "공시",
    "law": "법령",
    "performance": "실적",
    "action": "액션아이템",
    "insight": "AI 분석",
    "research": "자료실",
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


def search(connection, term, days=365, sources=None, limit=200):
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
        "performance": queries.search_performance_reports,
        "action": queries.search_action_items,
        "insight": queries.search_executive_insights,
        "research": queries.search_research_documents,
    }
    for source, search_func in dashboard_sources.items():
        if source not in enabled:
            continue
        for row in search_func(connection, term, days=days, limit=limit):
            items.append(_normalize_dashboard_item(source, row))

    items.sort(key=_sort_key, reverse=True)
    return items[: max(1, int(limit))]


def _normalize_dashboard_item(source, row):
    if source == "research":
        return {
            "source": source, "source_label": SOURCE_LABELS[source],
            "title": row.get("title") or row.get("original_filename") or "업로드 자료",
            "summary": row.get("ai_summary") or (row.get("extracted_text") or "")[:500],
            "occurred_at": row.get("report_date") or row.get("created_at"),
            "meta": " · ".join(filter(None, [row.get("company_name"), row.get("publisher")])),
            "url": f"/library/{row['id']}/download", "importance": None,
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
    if source == "performance":
        return {
            "source": source, "source_label": SOURCE_LABELS[source],
            "title": row.get("header_type") or "실적 보고",
            "summary": row.get("raw_text"),
            "occurred_at": row.get("received_at") or row.get("report_date"),
            "meta": row.get("report_date"), "url": None, "importance": None,
        }
    if source == "action":
        return {
            "source": source, "source_label": SOURCE_LABELS[source],
            "title": row.get("title") or "액션아이템",
            "summary": row.get("description") or row.get("memo") or row.get("ai_recommended_action"),
            "occurred_at": row.get("updated_at") or row.get("created_at"),
            "meta": " · ".join(filter(None, [row.get("owner"), row.get("status"), row.get("due_date")])),
            "url": "/action-items", "importance": row.get("priority"),
            "reported_by": row.get("reported_by"),
        }
    return {
        "source": source, "source_label": SOURCE_LABELS[source],
        "title": row.get("title") or "AI 분석",
        "summary": row.get("ai_interpretation") or row.get("facts") or row.get("recommended_action"),
        "occurred_at": row.get("created_at") or row.get("insight_date"),
        "meta": row.get("category"), "url": None, "importance": row.get("importance"),
    }
