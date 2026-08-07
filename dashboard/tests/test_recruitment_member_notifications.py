from scheduler import sync_recruitment_jobs


def test_recruitment_alert_contains_board_and_source_links(monkeypatch):
    monkeypatch.setattr(
        sync_recruitment_jobs.config,
        "DASHBOARD_PUBLIC_URL",
        "https://www.casinoin.kr",
    )
    message = sync_recruitment_jobs._recruitment_alert({
        "company_name": "인스파이어",
        "title": "카지노 채용",
        "deadline": "2026-08-31",
        "source_name": "INSPIRE Careers",
        "source_url": "https://example.com/job/1",
    })
    assert "인스파이어" in message
    assert "https://www.casinoin.kr/companies/recruitment" in message
    assert "https://example.com/job/1" in message
