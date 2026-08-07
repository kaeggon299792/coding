import pytest

from dashboard_db import queries, schema
from services import company_expert


def _insert(connection, company, metric, field, value):
    key = f"company_expert.{company}.{metric}.{field}"
    queries.upsert_source_data_series(
        connection,
        series_key=key,
        category="기업 전문정보",
        label=key,
        unit="배",
        frequency="snapshot",
        source_name="운영자 제공",
    )
    queries.upsert_source_data_point(
        connection,
        series_key=key,
        observation_date="2026-08-06",
        value=value,
        source_record_key=f"expert:{company}:{metric}:{field}:2026-08-06",
    )


def test_company_expert_reads_central_source_data(tmp_path):
    connection = schema.connect(str(tmp_path / "expert.db"))
    _insert(connection, "paradise", "per", "current", 10.69)
    _insert(connection, "paradise", "per", "median_5y", 17.12)
    _insert(connection, "paradise", "per", "industry_median", 11.08)
    connection.commit()
    dashboard = company_expert.build_dashboard(connection, "paradise")
    per = dashboard["metrics"][0]
    assert per["current"] == 10.69
    assert per["vs_5y"] == "낮음"
    assert per["vs_industry"] == "낮음"
    assert "주당순이익" in per["description"]
    assert dashboard["selected_company_name"] == "파라다이스"
    assert dashboard["as_of"] == "2026-08-06"
    connection.close()


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "expert-page.db"
    monkeypatch.setattr("config.DASHBOARD_DB_FILE", str(db_path))
    connection = schema.connect(str(db_path))
    _insert(connection, "gkl", "per", "current", 12.45)
    connection.commit()
    connection.close()
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_company_expert_page_is_public_and_filters_company(client):
    response = client.get("/companies/expert?company=gkl")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "기업 전문정보" in html
    assert "GKL" in html
    assert "12.45" in html
    assert "company-expert-page" in html
    assert "company-expert-command" in html
    assert "company-expert-kpis" in html
    assert "company-expert-group" in html
    assert "company-expert-card" in html
    assert "metric-help" in html
    assert "주가가 주당순이익" in html
    assert "????" not in html
    assert "company-expert-bars" not in html


def test_company_expert_labels_do_not_contain_mojibake():
    labels = list(company_expert.COMPANIES.values())
    labels += [label for _, label in company_expert.FIELDS]
    labels += list(company_expert.METRIC_DESCRIPTIONS.values())

    assert all("?" not in label for label in labels)
