from dashboard_db import queries
from services import source_data_repository


def test_source_repository_accumulates_and_aggregates(db_connection):
    queries.upsert_source_data_series(
        db_connection, series_key="test.sales", category="테스트", label="테스트 매출",
        unit="원", frequency="daily", aggregation="sum", source_name="테스트",
    )
    for day, value in (("2026-07-01", 10), ("2026-07-02", 20), ("2026-08-01", 30)):
        queries.upsert_source_data_point(
            db_connection, series_key="test.sales", observation_date=day,
            value=value, commit=True,
        )
    view = source_data_repository.build_view(
        db_connection, grain="monthly", start_date="2026-07-01",
        end_date="2026-08-31", selected_keys=["test.sales"],
    )
    assert view["periods"] == ["2026-07", "2026-08"]
    assert view["rows"][0]["values"] == [30.0, 30.0]


def test_internal_series_is_hidden_from_regular_users(db_connection):
    queries.upsert_source_data_series(
        db_connection, series_key="private.metric", category="경영실적", label="내부 지표",
        unit="원", frequency="daily", aggregation="sum", source_name="테스트",
        is_internal=True, commit=True,
    )
    assert queries.list_source_data_series(db_connection, include_internal=False) == []
    assert queries.list_source_data_series(db_connection, include_internal=True)[0]["series_key"] == "private.metric"


def test_existing_static_statistics_are_idempotently_backfilled(db_connection):
    assert source_data_repository.synchronize_existing_data(db_connection, force=True) is True
    first = queries.source_data_repository_stats(db_connection, include_internal=True)
    source_data_repository.synchronize_existing_data(db_connection, force=True)
    second = queries.source_data_repository_stats(db_connection, include_internal=True)
    assert first["point_count"] == second["point_count"]
    assert second["point_count"] > 100


def test_source_download_requires_login_and_renders_for_session(monkeypatch, tmp_path):
    import app as dashboard_app
    import config

    db_path = tmp_path / "route.db"
    monkeypatch.setattr(config, "DASHBOARD_DB_FILE", str(db_path))
    dashboard_app.app.config.update(TESTING=True)
    client = dashboard_app.app.test_client()
    anonymous = client.get("/resources/source-data")
    assert anonymous.status_code == 302
    assert "/login" in anonymous.location
    with client.session_transaction() as session:
        session["user_id"] = 999
        session["username"] = "viewer"
        session["role"] = "user"
    response = client.get("/resources/source-data")
    assert response.status_code == 200
    assert "데이터 다운" in response.get_data(as_text=True)
