import json
from pathlib import Path

from dashboard_db import schema
from scripts.import_paradise_vip_visits import STATE_KEY, import_paradise_vip_visits


DATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "paradise_vip_visits_20260806.json"
)


def test_paradise_vip_visits_import_is_complete_and_idempotent(tmp_path):
    database = tmp_path / "dashboard.db"
    first = import_paradise_vip_visits(database, DATA_FILE)
    second = import_paradise_vip_visits(database, DATA_FILE)

    assert first["point_count"] == second["point_count"] == 43
    assert first["integrity"] == second["integrity"] == "ok"

    connection = schema.connect(str(database))
    try:
        series = connection.execute(
            "SELECT label, unit, frequency FROM source_data_series WHERE series_key=?",
            ("epic.paradise_monthly_vip_visits.m01",),
        ).fetchone()
        points = connection.execute(
            "SELECT observation_date, value FROM source_data_points WHERE series_key=? ORDER BY observation_date",
            ("epic.paradise_monthly_vip_visits.m01",),
        ).fetchall()
        state = connection.execute(
            "SELECT state_value FROM source_data_repository_state WHERE state_key=?",
            (STATE_KEY,),
        ).fetchone()
    finally:
        connection.close()

    assert dict(series) == {
        "label": "파라다이스 그룹 VIP 방문일수",
        "unit": "방문일",
        "frequency": "monthly",
    }
    assert points[0]["observation_date"] == "2023-01-01"
    assert points[-1]["observation_date"] == "2026-07-01"
    assert points[-1]["value"] == 14881
    assert json.loads(state["state_value"])["point_count"] == 43
