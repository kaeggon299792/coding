from dashboard_db import queries
from services import government_notice_client
from app import _filter_legislation_items


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <ogLmPp>
    <ogLmPpSeq>80086</ogLmPpSeq>
    <lsNm>관광진흥법 시행규칙 일부개정령안 입법예고</lsNm>
    <lsClsNm>부령</lsClsNm>
    <asndOfiNm>문화체육관광부</asndOfiNm>
    <pntcNo>문화체육관광부공고 제2026-100호</pntcNo>
    <pntcDt>2026.07.30</pntcDt>
    <stYd>2026.07.30</stYd>
    <edYd>2026.09.08</edYd>
    <FileName>입법예고안.pdf</FileName>
    <FileDownLink>https://example.test/notice.pdf</FileDownLink>
    <readCnt>12</readCnt>
    <announceType>입법예고</announceType>
  </ogLmPp>
</result>""".encode("utf-8")


class FakeResponse:
    status_code = 200
    content = SAMPLE_XML


def test_search_normalize_and_store_government_notice(monkeypatch, db_connection):
    monkeypatch.setattr("config.LAWMAKING_API_OC", "approved-user")
    monkeypatch.setattr(
        "services.government_notice_client.get_with_hard_timeout",
        lambda *args, **kwargs: FakeResponse(),
    )

    result = government_notice_client.search_notices("카지노")
    assert result["ok"] is True
    notice = government_notice_client.normalize_notice(
        result["notices"][0], "카지노"
    )
    assert notice["notice_id"] == "80086"
    assert notice["ministry_name"] == "문화체육관광부"
    assert notice["detail_url"].endswith("/80086")
    assert notice["announcement_date"] == "2026-07-30"
    assert notice["start_date"] == "2026-07-30"
    assert notice["end_date"] == "2026-09-08"

    assert queries.upsert_government_legislative_notice(
        db_connection, notice
    ) is True
    assert queries.upsert_government_legislative_notice(
        db_connection, notice
    ) is False
    stored = queries.list_government_legislative_notices(db_connection)
    assert len(stored) == 1
    assert stored[0]["notice_name"].startswith("관광진흥법")


def test_api_auth_error_is_reported(monkeypatch):
    class AuthErrorResponse:
        status_code = 200
        content = b"<result><retMsg>401</retMsg></result>"

    monkeypatch.setattr("config.LAWMAKING_API_OC", "not-approved")
    monkeypatch.setattr(
        "services.government_notice_client.get_with_hard_timeout",
        lambda *args, **kwargs: AuthErrorResponse(),
    )
    result = government_notice_client.search_notices("카지노")
    assert result == {
        "ok": False,
        "error": "API 인증 또는 요청 오류(401)",
    }


def test_xml_entities_are_rejected_without_expansion(monkeypatch):
    class EntityResponse:
        status_code = 200
        content = b'<!DOCTYPE x [<!ENTITY payload "expanded">]><result>&payload;</result>'

    monkeypatch.setattr("config.LAWMAKING_API_OC", "approved-user")
    monkeypatch.setattr(
        "services.government_notice_client.get_with_hard_timeout",
        lambda *args, **kwargs: EntityResponse(),
    )

    result = government_notice_client.search_notices("casino")

    assert result == {
        "ok": False,
        "error": "정부입법예고 API 응답이 XML 형식이 아닙니다.",
    }


def test_legislation_filters_source_status_importance_and_query():
    government = [{
        "notice_name": "관광진흥법 시행령 입법예고",
        "ministry_name": "문화체육관광부",
        "announcement_date": "2026-05-12",
        "is_open": 0,
    }]
    assembly = [
        {
            "bill_name": "관광진흥법 일부개정법률안",
            "proposer_name": "테스트 의원",
            "proposed_date": "2026-07-31",
            "process_stage": "위원회 심사",
            "impact_level": "high",
        },
        {
            "bill_name": "종료된 법률안",
            "proposed_date": "2025-01-01",
            "pass_status": "철회",
            "impact_level": "low",
        },
    ]

    high_open = _filter_legislation_items(
        government, assembly,
        source="all", status="open", importance="high", query="테스트",
    )
    assert len(high_open) == 1
    assert high_open[0]["source"] == "assembly"
    assert high_open[0]["record"]["bill_name"].startswith("관광진흥법")

    closed_government = _filter_legislation_items(
        government, assembly,
        source="government", status="closed", importance="normal", query="문체부",
    )
    assert closed_government == []

    closed_government = _filter_legislation_items(
        government, assembly,
        source="government", status="closed", importance="normal", query="문화체육",
    )
    assert len(closed_government) == 1
