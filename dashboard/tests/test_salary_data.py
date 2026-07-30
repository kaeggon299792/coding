from dashboard_db import queries, schema
from services import salary_data


def test_salary_source_parsers():
    salary, period = salary_data._parse_jobkorea(
        '<meta name="title" content="파라다이스 연봉정보 - 평균연봉 8,024만원">'
        '<div>2025년 기준</div>'
    )
    assert (salary, period) == (8024, "2025")
    salary, period = salary_data._parse_openbiz(
        '<meta name="description" content="2026년 5월 기준 추정 평균 연봉은 약 3,921만원">'
    )
    assert (salary, period) == (3921, "2026.05")


def test_salary_snapshots_keep_monthly_history(tmp_path):
    connection = schema.connect(tmp_path / "salary.db")
    base = {
        "entity_code": "paradise",
        "entity_name": "파라다이스",
        "entity_type": "company",
        "source_name": "테스트",
        "source_url": "https://example.com",
        "source_period": "2025",
    }
    for day, value in (("2026-06-30", 7900), ("2026-07-01", 8000), ("2026-07-30", 8024)):
        queries.upsert_salary_snapshot(
            connection,
            {**base, "average_salary_manwon": value, "collected_date": day,
             "fetched_at": f"{day}T09:00:00+09:00"},
        )
    item = queries.list_salary_dashboard(connection)[0]
    assert [row["average_salary_manwon"] for row in item["monthly_history"]] == [7900, 8024]
    assert item["monthly_change"] == 124
    assert item["trend_points"]
    connection.close()


def test_salary_page_is_public():
    from app import app

    app.testing = True
    response = app.test_client().get("/performance/salaries")
    assert response.status_code == 200
    assert "연봉 정보".encode() in response.data


def test_recruitment_page_is_public_and_searchable(monkeypatch, tmp_path):
    from app import app
    import config
    from extensions import dashboard_db

    monkeypatch.setattr(config, "DASHBOARD_DB_FILE", str(tmp_path / "recruitment.db"))
    app.testing = True
    connection = dashboard_db()
    queries.upsert_recruitment_job(connection, {
        "source_name": "잡코리아", "source_job_id": "job-1",
        "company_name": "파라다이스", "title": "카지노 딜러 채용",
        "employment_type": "계약직", "location": "서울",
        "deadline": "2026-08-31", "compensation_summary": "연봉 4,000만원",
        "benefits_summary": "식사 제공", "ai_summary": "계약직 공고입니다.",
        "treatment_level": "보통", "source_url": "https://example.com/job-1",
        "raw_text": "카지노 계약직", "posted_at": "2026-07-30",
        "first_seen_at": "2026-07-30T09:00:00+09:00",
        "last_seen_at": "2026-07-30T09:00:00+09:00",
        "analyzed_at": None, "analysis_error": None,
    })
    connection.close()
    response = app.test_client().get("/performance/recruitment?q=딜러")
    assert response.status_code == 200
    assert "카지노 딜러 채용".encode() in response.data
