import json
from types import SimpleNamespace

from services import gemini_news


def test_metadata_prefers_successful_url_context():
    payload = {
        "candidates": [{
            "urlContextMetadata": {"urlMetadata": [{
                "retrievedUrl": "https://example.com/a",
                "urlRetrievalStatus": "URL_RETRIEVAL_STATUS_SUCCESS",
            }]},
            "groundingMetadata": {"groundingChunks": [{
                "web": {"uri": "https://example.com/a", "title": "Source A"}
            }]},
        }]
    }
    basis, statuses, citations = gemini_news._metadata(payload)
    assert basis == "full_text"
    assert statuses == ["URL_RETRIEVAL_STATUS_SUCCESS"]
    assert citations == [{"url": "https://example.com/a", "title": "Source A"}]


def test_normalize_uses_search_grounding_when_url_failed(monkeypatch):
    monkeypatch.setattr(gemini_news.config, "GEMINI_MODEL", "gemini-test")
    payload = {
        "candidates": [{
            "urlContextMetadata": {"urlMetadata": [{
                "urlRetrievalStatus": "URL_RETRIEVAL_STATUS_ERROR"
            }]},
            "groundingMetadata": {"groundingChunks": [{
                "web": {"uri": "https://source.test/story", "title": "Story"}
            }]},
        }]
    }
    result = gemini_news._normalize_result(
        {
            "title_ko": "제목", "summary_ko": "요약", "category": "규제·정책",
            "impact_direction": "negative", "importance_score": 81,
            "ai_analysis": "영향", "canonical_url": "javascript:alert(1)",
        },
        payload,
        {"original_title": "Original", "original_url": "https://fallback.test/a"},
    )
    assert result["analysis_basis"] == "search_grounded"
    assert result["canonical_url"] == "https://fallback.test/a"
    assert json.loads(result["source_citations_json"])[0]["url"] == "https://source.test/story"


def test_parse_json_text_accepts_fenced_json():
    assert gemini_news._parse_json_text('```json\n{"importance_score": 50}\n```')["importance_score"] == 50


def test_grounding_redirect_is_resolved_without_fetching_publisher(monkeypatch):
    monkeypatch.setattr(
        gemini_news.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=302,
            headers={"Location": "https://publisher.example/story"},
        ),
    )
    rows = gemini_news._resolve_grounding_citations([{
        "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/token",
        "title": "Publisher",
    }])
    assert rows == [{"url": "https://publisher.example/story", "title": "Publisher"}]
