"""
OpenAI 클라이언트가 실제로 이 코드가 필요로 하는 형태로 동작하는지 확인하는 테스트.

과거 PythonAnywhere 실배포에서 두 가지 의존성 버전 문제가 실제로 발생했다:
1. openai==1.51.0 + httpx>=0.28 조합 -> "Client.__init__() got an unexpected
   keyword argument 'proxies'" (httpx가 옛 openai SDK가 넘기던 인자를 제거함)
2. openai==1.51.0 -> client.responses(Responses API)가 아예 없음(이후 SDK에
   추가된 기능이라 그 버전엔 없었음)
이 테스트들은 두 문제를 다시 놓치지 않도록 클라이언트 생성과 responses 속성
존재 여부를 검증한다(실제 API 호출은 하지 않음).
"""

import json
from datetime import timedelta
from types import SimpleNamespace

from dashboard_db import queries
from services import ai_insights
from utils import now_kst


def test_openai_client_can_be_constructed(monkeypatch):
    monkeypatch.setattr("config.OPENAI_API_KEY", "test-key-not-real")
    ai_insights._client = None  # 이전 테스트에서 캐시된 클라이언트가 있으면 초기화

    client = ai_insights._get_client()
    assert client is not None


def test_openai_client_supports_responses_api(monkeypatch):
    """이 코드는 client.responses.create()를 사용하므로 그 속성이 반드시 있어야 한다."""
    monkeypatch.setattr("config.OPENAI_API_KEY", "test-key-not-real")
    ai_insights._client = None

    client = ai_insights._get_client()
    assert hasattr(client, "responses"), (
        "설치된 openai 패키지 버전이 Responses API(client.responses)를 지원하지 않습니다. "
        "requirements.txt의 openai 버전을 확인하세요."
    )


def test_summarize_disclosure_without_key_returns_error_not_exception(db_connection, monkeypatch):
    monkeypatch.setattr("config.OPENAI_API_KEY", "")
    result = ai_insights.summarize_disclosure(db_connection, {"corp_name": "테스트기업", "report_nm": "사업보고서"})
    assert result["ai_summary"] is None
    assert result["error"] is not None


def test_manual_document_analysis_can_bypass_internal_daily_limit(
    db_connection, monkeypatch
):
    monkeypatch.setattr("config.OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr("config.OPENAI_INSIGHT_MODEL", "test-model")
    monkeypatch.setattr(
        ai_insights,
        "_check_daily_limits",
        lambda connection, request_type: (_ for _ in ()).throw(
            ai_insights.DailyLimitExceeded("daily limit")
        ),
    )

    blocked, blocked_error = ai_insights.analyze_research_document(
        db_connection, {"extracted_text": "본문"}
    )
    assert blocked is None
    assert blocked_error == "daily limit"

    called = []
    monkeypatch.setattr(
        ai_insights,
        "_call",
        lambda *args, **kwargs: called.append(kwargs["bypass_daily_limits"])
        or ({"ai_summary": "완료"}, None),
    )
    result, error = ai_insights.analyze_research_document(
        db_connection,
        {"extracted_text": "본문"},
        bypass_daily_limits=True,
    )
    assert result == {"ai_summary": "완료"}
    assert error is None
    assert called == [True]


def test_daily_limit_sends_one_detailed_telegram_alert(
    db_connection, monkeypatch
):
    monkeypatch.setattr("config.OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr("config.OPENAI_INSIGHT_MODEL", "test-model")
    monkeypatch.setattr("config.MAX_GPT_CALLS_PER_DAY", 0)
    monkeypatch.setattr(ai_insights, "get_daily_call_limit", lambda connection: 0)
    sent = []
    monkeypatch.setattr(
        ai_insights.telegram_alert,
        "send_alert",
        lambda message, *, force=False: sent.append((message, force)) or True,
    )

    for _ in range(2):
        result, error = ai_insights.analyze_research_document(
            db_connection, {"extracted_text": "본문"}
        )
        assert result is None
        assert "하루 GPT 호출 한도" in error

    assert len(sent) == 1
    assert sent[0][1] is True
    assert "CASINO IN GPT 내부 한도 초과" in sent[0][0]
    assert "research_document_analysis" in sent[0][0]
    assert "현재 호출" in sent[0][0]
    assert "예상 비용" in sent[0][0]
    row = db_connection.execute(
        "SELECT sent_at FROM ai_limit_alerts WHERE limit_type='call_count'"
    ).fetchone()
    assert row["sent_at"]


def test_admin_limit_setting_and_reset_preserve_usage_log(db_connection):
    ai_insights.set_daily_call_limit(db_connection, 321, actor_id=None)
    assert ai_insights.get_daily_call_limit(db_connection) == 321
    queries.record_api_usage(
        db_connection, "test-model", "test-call", 10, 5, 0.01, True,
        request_summary="request", response_summary='{"ok":true}',
    )
    assert queries.get_today_usage_summary(db_connection)["call_count"] == 1

    ai_insights.reset_today_usage(db_connection)

    assert queries.get_today_usage_summary(db_connection)["call_count"] == 0
    assert db_connection.execute(
        "SELECT COUNT(*) FROM api_usage WHERE request_type='test-call'"
    ).fetchone()[0] == 1


def test_purpose_settings_use_independent_models_and_limits(db_connection):
    from services import ai_runtime_settings

    saved = ai_runtime_settings.save_purpose_settings(
        db_connection,
        "news_importance",
        {
            "enabled": "1",
            "model": "gpt-news-purpose-test",
            "daily_call_limit": "7",
            "importance_threshold": "65",
            "web_importance_threshold": "82",
        },
    )
    db_connection.commit()
    assert saved["model"] == "gpt-news-purpose-test"
    assert saved["daily_call_limit"] == 7
    assert saved["importance_threshold"] == 65
    assert saved["web_importance_threshold"] == 82
    assert ai_runtime_settings.classify_request_type(
        "overseas_news_translation_analysis_ko"
    ) == "news_importance"
    assert ai_runtime_settings.classify_request_type(
        "localization_translation_ja"
    ) == "translation"

    for index in range(2):
        queries.record_api_usage(
            db_connection, "model", "overseas_news_translation_analysis_ko",
            1, 1, 0.01, True,
        )
    queries.record_api_usage(
        db_connection, "model", "localization_translation_ja", 1, 1, 0.02, True,
    )
    news_usage = ai_runtime_settings.get_purpose_usage(
        db_connection, "news_importance"
    )
    translation_usage = ai_runtime_settings.get_purpose_usage(
        db_connection, "translation"
    )
    assert news_usage == {"call_count": 2, "total_cost": 0.02}
    assert translation_usage == {"call_count": 1, "total_cost": 0.02}


def test_log_retention_removes_only_entries_older_than_30_days(db_connection):
    old = (now_kst() - timedelta(days=31)).isoformat()
    recent = (now_kst() - timedelta(days=1)).isoformat()
    db_connection.executemany(
        """INSERT INTO errors(occurred_at,stage,error_type,error_message)
           VALUES (?, 'test', 'test', 'test')""",
        [(old,), (recent,)],
    )
    db_connection.commit()

    queries.purge_logs_older_than(db_connection, days=30)
    db_connection.commit()

    rows = db_connection.execute(
        "SELECT occurred_at FROM errors ORDER BY occurred_at"
    ).fetchall()
    assert [row["occurred_at"] for row in rows] == [recent]


def test_important_overseas_news_uses_low_context_web_search(
    db_connection, monkeypatch
):
    monkeypatch.setattr("config.OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr("config.OPENAI_NEWS_MODEL", "gpt-news-test")
    captured = {}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                output_text=json.dumps({
                    "title_ko": "검증 제목", "summary_ko": "검증 요약",
                    "category": "실적·시장", "impact_direction": "positive",
                    "importance_score": 90, "ai_analysis": "검증 분석",
                    "canonical_url": "https://publisher.example/story",
                    "source_urls": ["https://publisher.example/story"],
                }),
            )

    monkeypatch.setattr(
        ai_insights, "_get_client", lambda: SimpleNamespace(responses=Responses())
    )
    result, error = ai_insights.analyze_important_overseas_news_with_web(
        db_connection,
        {
            "region": "macau", "publisher": "Publisher",
            "original_title": "Important casino news",
            "original_summary": "Summary", "original_url": "https://example.com/rss",
        },
    )
    assert error is None
    assert result["importance_score"] == 90
    assert captured["model"] == "gpt-news-test"
    assert captured["tools"] == [{"type": "web_search", "search_context_size": "low"}]
