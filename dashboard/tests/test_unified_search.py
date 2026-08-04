from dashboard_db import queries
from services import unified_search


def test_dashboard_search_sources_are_normalized_and_sorted(db_connection, monkeypatch):
    monkeypatch.setattr(
        "services.unified_search.news_reader.search_articles",
        lambda *args, **kwargs: [
            {
                "title": "영종도 복합리조트 투자",
                "publisher": "테스트뉴스",
                "latest_summary": "투자 확대",
                "published_at": "2026-07-24T09:00:00+00:00",
                "original_url": "https://example.com/news",
                "importance": "high",
            }
        ],
    )
    queries.create_action_item(
        db_connection,
        title="영종도 투자 검토",
        description="사업성 재검토",
    )

    results = unified_search.search(
        db_connection,
        "영종도",
        sources=["news", "action"],
    )

    assert {item["source"] for item in results} == {"news", "action"}
    assert all(item["title"] for item in results)
    action = next(item for item in results if item["source"] == "action")
    assert action["url"].startswith("/board/bug-reports/")
    assert results == sorted(results, key=unified_search._sort_key, reverse=True)


def test_blank_unified_search_returns_empty(db_connection):
    assert unified_search.search(db_connection, "   ") == []


def test_research_documents_are_in_unified_search(db_connection):
    queries.create_research_document(
        db_connection,
        company_name="파라다이스",
        title="영종도 카지노 전망",
        original_filename="report.pdf",
        stored_filename="research.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256="b" * 64,
        extracted_text="영종도 외국인 관광객 회복",
        extraction_status="complete",
    )

    results = unified_search.search(
        db_connection, "영종도", sources=["research"]
    )

    assert len(results) == 1
    assert results[0]["source"] == "research"
    assert results[0]["url"].startswith("/companies/reports/")
    assert results[0]["url"].endswith("/download")


def test_search_filter_uses_dedicated_responsive_class():
    from pathlib import Path

    dashboard_dir = Path(__file__).resolve().parents[1]
    template = (dashboard_dir / "templates" / "search.html").read_text(encoding="utf-8")
    css = (dashboard_dir / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")
    assert 'class="search-source-filter"' in template
    assert '.search-source-filter input[type="checkbox"]' in css
