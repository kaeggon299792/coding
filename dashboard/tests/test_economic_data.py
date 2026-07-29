from dashboard_db import queries


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
