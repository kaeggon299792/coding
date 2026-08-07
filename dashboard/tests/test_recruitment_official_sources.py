import json

from dashboard_db import queries
from services import recruitment_data


def test_parse_inspire_jobs_uses_visible_official_openings_only():
    payload = {"props": {"pageProps": {"items": [
        {"openingId": 123, "title": "카지노 딜러", "openDate": "2026-08-01T00:00:00Z",
         "dueDate": "2026-08-20T00:00:00Z", "group": {"name": "인스파이어"},
         "workspaceDivision": {"division": "Casino Operations"}},
        {"openingId": 999, "title": "숨겨진 공고"},
    ]}}}
    markup = '<a href="/ko/o/123">공고</a><script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + '</script>'
    jobs = recruitment_data.parse_inspire_jobs(markup, "2026-08-07T12:00:00+09:00")
    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "123"
    assert jobs[0]["company_name"] == "인스파이어"
    assert jobs[0]["source_url"].endswith("/ko/o/123")


def test_parse_paradise_jobs_keeps_stable_identity_and_dates():
    xml = '''<?xml version="1.0" encoding="utf-8"?><SHEET><DATA KEY="default">
    <HTR><TD>C_CD</TD><TD>ANN_TITLE</TD><TD>ANN_SEQ_NO</TD><TD>RE_NO</TD><TD>COM_NM</TD><TD>RE_TYPE_NM</TD><TD>GIGAN</TD><TD>STATUS</TD></HTR>
    <TR><TD>WCA</TD><TD>딜러 모집</TD><TD>1</TD><TD>672</TD><TD>파라다이스 카지노 워커힐</TD><TD>수시</TD><TD>2026.08.05~2026.08.19</TD><TD>접수중</TD></TR>
    </DATA></SHEET>'''
    jobs = recruitment_data.parse_paradise_jobs(xml, "2026-08-07T12:00:00+09:00")
    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "WCA:672:1"
    assert jobs[0]["posted_at"] == "2026.08.05"
    assert jobs[0]["deadline"] == "2026.08.19"


def test_collect_official_sources_isolates_source_failures(monkeypatch):
    monkeypatch.setattr(recruitment_data, "_get", lambda _url: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(recruitment_data, "_post", lambda _url, **_kwargs: '<SHEET><DATA KEY="default"><HTR><TD>C_CD</TD></HTR></DATA></SHEET>')
    items, errors = recruitment_data.collect_official_sources()
    assert items == []
    assert len(errors) == 1
    assert errors[0].startswith("인스파이어 공식채용:")


def test_company_inference_covers_major_casino_operators():
    assert recruitment_data._infer_company_name("제주 드림타워 카지노 채용") == "롯데관광개발"
    assert recruitment_data._infer_company_name("INSPIRE dealer") == "인스파이어"
    assert recruitment_data._infer_company_name("세븐럭 카지노") == "GKL"


def test_recruitment_defaults_to_registration_order_and_supports_deadline(db_connection):
    base = {
        "employment_type": "정규직", "location": "서울",
        "compensation_summary": "명시 없음", "benefits_summary": "명시 없음",
        "ai_summary": "요약", "treatment_level": "판단불가",
        "raw_text": "채용", "analyzed_at": None, "analysis_error": None,
    }
    for item in (
        {"source_name": "파라다이스 공식채용", "source_job_id": "p1", "company_name": "파라다이스", "title": "늦게 등록", "source_url": "https://example.com/p1", "posted_at": "2026-07-01", "deadline": "2026.08.30", "first_seen_at": "2026-08-07T12:00:00+09:00", "last_seen_at": "2026-08-07T12:00:00+09:00"},
        {"source_name": "인스파이어 공식채용", "source_job_id": "i1", "company_name": "인스파이어", "title": "먼저 마감", "source_url": "https://example.com/i1", "posted_at": "2026-08-06", "deadline": "2026-08-10", "first_seen_at": "2026-08-06T12:00:00+09:00", "last_seen_at": "2026-08-07T12:00:00+09:00"},
    ):
        queries.upsert_recruitment_job(db_connection, {**base, **item})

    registered = queries.list_recruitment_jobs(db_connection)
    deadline = queries.list_recruitment_jobs(db_connection, sort="deadline")
    paradise = queries.list_recruitment_jobs(db_connection, company="파라다이스")
    options = queries.list_recruitment_filter_options(db_connection)

    assert [item["title"] for item in registered] == ["늦게 등록", "먼저 마감"]
    assert [item["title"] for item in deadline] == ["먼저 마감", "늦게 등록"]
    assert [item["company_name"] for item in paradise] == ["파라다이스"]
    assert options["companies"] == ["파라다이스", "인스파이어"]
    assert options["sources"] == ["인스파이어 공식채용", "파라다이스 공식채용"]
