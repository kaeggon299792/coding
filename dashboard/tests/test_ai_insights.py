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

from services import ai_insights


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
