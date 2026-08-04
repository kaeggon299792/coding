from dashboard_db import queries, schema
from services import salary_data
from services import casino_industry


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


def test_employer_review_parsers():
    rating, count = salary_data._parse_blind_rating(
        '<script type="application/ld+json">'
        '{"@type":"EmployerAggregateRating","ratingValue":"2.9",'
        '"ratingCount":415}</script>'
    )
    assert (rating, count) == (2.9, 415)
    rating, count = salary_data._parse_jobplanet_rating(
        '<title>(주)파라다이스 기업리뷰 88건, 3.2 리뷰평점</title>'
    )
    assert (rating, count) == (3.2, 88)


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


def test_employer_ratings_are_daily_and_enter_central_repository(tmp_path):
    connection = schema.connect(tmp_path / "ratings.db")
    base = {
        "entity_code": "paradise",
        "entity_name": "파라다이스",
        "source_code": "blind",
        "source_name": "블라인드",
        "source_url": "https://example.com/blind",
        "collected_date": "2026-08-01",
        "fetched_at": "2026-08-01T09:00:00+09:00",
    }
    queries.upsert_employer_review_snapshot(
        connection, {**base, "rating": 2.9, "review_count": 411}
    )
    queries.upsert_employer_review_snapshot(
        connection, {**base, "rating": 3.0, "review_count": 412}
    )
    rows = connection.execute("SELECT * FROM employer_review_snapshots").fetchall()
    assert len(rows) == 1
    assert rows[0]["rating"] == 3.0
    point = connection.execute(
        "SELECT * FROM source_data_points WHERE series_key=?",
        ("employer_rating.paradise.blind",),
    ).fetchone()
    assert point["value"] == 3.0
    connection.close()


def test_review_only_company_is_returned_without_salary(tmp_path):
    connection = schema.connect(tmp_path / "review-only.db")
    queries.upsert_employer_review_snapshot(connection, {
        "entity_code": "inspire", "entity_name": "인스파이어 인티그레이티드 리조트",
        "source_code": "blind", "source_name": "블라인드 · 인스파이어",
        "source_url": "https://example.com/inspire", "rating": 3.2,
        "review_count": 164, "collected_date": "2026-08-01",
        "fetched_at": "2026-08-01T09:00:00+09:00",
    })
    item = next(
        row for row in queries.list_salary_dashboard(connection)
        if row["entity_code"] == "inspire"
    )
    assert item["average_salary_manwon"] is None
    assert item["review_ratings"][0]["rating"] == 3.2
    connection.close()


def test_all_casino_operators_are_kept_when_public_data_is_missing():
    operators = casino_industry.list_operator_companies()
    items = salary_data.merge_operator_cards(
        [{
            "entity_code": "paradise", "entity_name": "파라다이스",
            "entity_type": "company", "average_salary_manwon": 8000,
            "review_ratings": [],
        }],
        operators,
    )
    operator_items = [item for item in items if item["entity_type"] == "company"]
    assert len(operators) == 13
    assert len(operator_items) == 13
    assert next(item for item in items if item["entity_code"] == "paradise")["venue_count"] == 3
    inspire = next(item for item in items if item["entity_code"] == "inspire")
    assert inspire["average_salary_manwon"] is None
    assert inspire["data_available"] is False


def test_venue_specific_rating_sources_are_included():
    sources = {
        (item["entity_code"], item["source_code"]): item
        for item in salary_data.REVIEW_SOURCES
    }
    assert "/companies/44165/reviews/" in sources[("gkl", "jobplanet")]["url"]
    assert "/companies/316912/reviews/" in sources[("gkl", "jobplanet_sevenluck")]["url"]
    assert "세븐럭카지노" in sources[("gkl", "jobplanet_sevenluck")]["source_name"]
    assert sources[("lotte_tour", "jobplanet_dreamtower")]["source_name"].endswith("제주드림타워")
    assert sources[("lotte_tour", "blind_dreamtower")]["source_name"].endswith("제주드림타워")
    assert "/companies/148195/reviews/" in sources[("paradise_segasammy", "jobplanet")]["url"]
    assert sources[("paradise_segasammy", "blind")]["source_name"].endswith("파라다이스세가사미")
    assert "/companies/393355/reviews/" in sources[("inspire", "jobplanet")]["url"]
    assert sources[("inspire", "blind")]["source_name"].endswith("인스파이어")
    assert "/companies/141004/reviews/" in sources[("golden_crown", "jobplanet_interburgo")]["url"]
    assert "(참고)" in sources[("golden_crown", "blind_interburgo")]["source_name"]
    assert "/companies/361539/reviews/" in sources[("paradise", "jobplanet_glad")]["url"]
    assert "글래드호텔앤리조트(참고)" in sources[("paradise", "blind_glad")]["source_name"]


def test_four_major_casino_companies_are_sorted_first():
    operators = casino_industry.list_operator_companies()
    existing = [
        {"entity_code": code, "entity_name": code, "entity_type": "company",
         "average_salary_manwon": 1, "review_ratings": []}
        for code in ("kangwon_land", "paradise", "gkl", "lotte_tour")
    ]
    items = salary_data.merge_operator_cards(existing, operators)
    assert [item["entity_code"] for item in items[:4]] == [
        "paradise", "gkl", "kangwon_land", "lotte_tour"
    ]


def test_salary_page_is_public():
    from app import app

    app.testing = True
    response = app.test_client().get("/companies/salary-ratings")
    assert response.status_code == 200
    assert "연봉·평점".encode() in response.data


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
    response = app.test_client().get("/companies/recruitment?q=딜러")
    assert response.status_code == 200
    assert "카지노 딜러 채용".encode() in response.data
