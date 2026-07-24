"""
OpenAI 클라이언트 생성 자체가 되는지 확인하는 테스트.

과거에 openai==1.51.0 + httpx>=0.28 조합에서 "Client.__init__() got an
unexpected keyword argument 'proxies'" 오류가 났었다(실제 PythonAnywhere
배포에서 발견됨). 이 테스트는 그런 의존성 버전 비호환을 다시 놓치지 않도록
클라이언트 생성 자체를 검증한다(실제 API 호출은 하지 않음).
"""

from services import ai_insights


def test_openai_client_can_be_constructed(monkeypatch):
    monkeypatch.setattr("config.OPENAI_API_KEY", "test-key-not-real")
    ai_insights._client = None  # 이전 테스트에서 캐시된 클라이언트가 있으면 초기화

    client = ai_insights._get_client()
    assert client is not None


def test_summarize_disclosure_without_key_returns_error_not_exception(db_connection, monkeypatch):
    monkeypatch.setattr("config.OPENAI_API_KEY", "")
    result = ai_insights.summarize_disclosure(db_connection, {"corp_name": "테스트기업", "report_nm": "사업보고서"})
    assert result["ai_summary"] is None
    assert result["error"] is not None
