from services import law_client


def test_get_law_text_without_keys_returns_error_not_exception(monkeypatch):
    monkeypatch.setattr("config.LAW_API_OC", "")
    monkeypatch.setattr("config.LAW_API_KEY", "")
    result = law_client.get_law_text("123456")
    assert result["ok"] is False
    assert "LAW_API_OC" in result["error"]


def test_compute_snapshot_hash_changes_when_article_content_changes():
    law_v1 = {"법령": {"조문": {"조문단위": [{"조문번호": "1", "조문제목": "목적", "조문내용": "이 법은 ..."}]}}}
    law_v2 = {"법령": {"조문": {"조문단위": [{"조문번호": "1", "조문제목": "목적", "조문내용": "이 법은 (개정) ..."}]}}}

    hash1 = law_client.compute_snapshot_hash(law_v1)
    hash2 = law_client.compute_snapshot_hash(law_v2)
    hash1_again = law_client.compute_snapshot_hash(law_v1)

    assert hash1 != hash2
    assert hash1 == hash1_again


def test_extract_dates_reads_basic_info():
    law_data = {"법령": {"기본정보": {"공포일자": "20260101", "시행일자": "20260701"}}}
    dates = law_client.extract_dates(law_data)
    assert dates["promulgation_date"] == "20260101"
    assert dates["effective_date"] == "20260701"


def test_select_exact_candidate_ignores_similarly_named_laws():
    candidates = [
        {"law_name": "관광진흥법 시행령", "mst": "999", "promulgation_date": "20260801"},
        {"law_name": "관광진흥법", "mst": "100", "promulgation_date": "20250701"},
        {"law_name": "관광진흥법", "mst": "101", "promulgation_date": "20260730"},
    ]

    selected = law_client.select_exact_candidate(candidates, "관광진흥법")

    assert selected["mst"] == "101"


def test_select_exact_candidate_returns_none_without_exact_match():
    selected = law_client.select_exact_candidate(
        [{"law_name": "관광진흥법 시행규칙", "mst": "123"}], "관광진흥법"
    )

    assert selected is None


def test_network_error_does_not_raise(monkeypatch):
    import requests

    monkeypatch.setattr("config.LAW_API_OC", "test-oc")
    monkeypatch.setattr("config.LAW_API_KEY", "test-key")

    def raise_error(*a, **k):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("requests.get", raise_error)

    result = law_client.search_law("관광진흥법")
    assert result["ok"] is False
