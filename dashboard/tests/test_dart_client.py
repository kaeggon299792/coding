from services import dart_client


def test_is_important_disclosure_matches_keyword():
    assert dart_client.is_important_disclosure("주요사항보고서(유상증자결정)")
    assert dart_client.is_important_disclosure("사업보고서")
    assert not dart_client.is_important_disclosure("임원ㆍ주요주주특정증권등소유상황보고서")  # 키워드 미포함 예시


def test_build_dart_link_format():
    link = dart_client.build_dart_link("20260724000123")
    assert link == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000123"


def test_search_disclosures_without_api_key_returns_error_not_exception(monkeypatch):
    monkeypatch.setattr("config.DART_API_KEY", "")
    result = dart_client.search_disclosures(corp_code="00126380")
    assert result["ok"] is False
    assert "DART_API_KEY" in result["error"]


def test_search_disclosures_handles_no_data_status_gracefully(monkeypatch):
    monkeypatch.setattr("config.DART_API_KEY", "dummy-key")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "013", "message": "조회된 데이터가 없습니다."}

    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse())

    result = dart_client.search_disclosures(corp_code="00126380")
    assert result["ok"] is True
    assert result["list"] == []


def test_search_disclosures_network_error_does_not_raise(monkeypatch):
    import requests

    monkeypatch.setattr("config.DART_API_KEY", "dummy-key")

    def raise_error(*a, **k):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("requests.get", raise_error)

    result = dart_client.search_disclosures(corp_code="00126380")
    assert result["ok"] is False
    assert "네트워크 오류" in result["error"]
