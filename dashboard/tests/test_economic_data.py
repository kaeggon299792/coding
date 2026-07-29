from dashboard_db import queries
from services import economic_data


def test_economic_series_builds_gradient_chart(db_connection):
    for date, value in (("20260727", 1400.0), ("20260728", 1410.0), ("20260729", 1405.0)):
        queries.upsert_economic_observation(db_connection, {
            "series_code": "FX_USD", "observation_date": date,
            "label": "미국 달러", "category": "exchange", "value": value,
            "unit": "원", "source": "한국수출입은행",
        })
    rows = queries.list_economic_series(db_connection)
    assert len(rows) == 1
    assert rows[0]["latest"] == 1405.0
    assert rows[0]["change"] == -5.0
    assert rows[0]["points"]
    assert rows[0]["area_points"].endswith("100,40")


def test_opinet_uses_code_parameter_and_date_field(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "RESULT": {
                    "OIL": [
                        {"DATE": "20260729", "PRODCD": "B027", "PRICE": "1,871.74"}
                    ]
                }
            }

    def fake_get(url, **kwargs):
        captured.update(kwargs["params"])
        return Response()

    monkeypatch.setattr("config.OPINET_API_KEY", "test-key")
    monkeypatch.setattr("services.economic_data.get_with_hard_timeout", fake_get)

    result = economic_data.fetch_oil()

    assert captured == {"out": "json", "code": "test-key"}
    assert result["errors"] == []
    assert result["items"][0]["observation_date"] == "20260729"
    assert result["items"][0]["value"] == 1871.74


def test_economic_changed_at_only_moves_when_value_changes(db_connection):
    item = {
        "series_code": "FX_USD", "observation_date": "20260729",
        "label": "미국 달러", "category": "exchange", "value": 1400.0,
        "unit": "원", "source": "한국수출입은행",
    }
    queries.upsert_economic_observation(db_connection, item)
    first = dict(db_connection.execute(
        "SELECT * FROM economic_series WHERE series_code='FX_USD'"
    ).fetchone())
    queries.upsert_economic_observation(db_connection, item)
    unchanged = dict(db_connection.execute(
        "SELECT * FROM economic_series WHERE series_code='FX_USD'"
    ).fetchone())
    assert unchanged["changed_at"] == first["changed_at"]

    queries.upsert_economic_observation(db_connection, {**item, "value": 1401.0})
    changed = dict(db_connection.execute(
        "SELECT * FROM economic_series WHERE series_code='FX_USD'"
    ).fetchone())
    assert changed["value"] == 1401.0
    assert changed["changed_at"] >= unchanged["changed_at"]
