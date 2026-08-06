import copy
import json
from pathlib import Path

import pytest
from dashboard_db import schema
from scripts.import_epic_industry_data import STATE_KEY, import_epic_data

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "epic_industry_metrics_20260806.json"


def _payload(value=10):
    aliases = [
        {"filename": f"source-{number:02d}.xlsx", "sha256": f"{number:064x}", "size": 100}
        for number in range(1, 53)
    ]
    return {
        "schema_version": 1,
        "generated_on": "2026-08-06",
        "source_file_count": 52,
        "unique_dataset_count": 1,
        "datasets": [{
            "dataset_id": "sample_monthly_revenue",
            "label": "예시 월별 매출액",
            "category": "테스트",
            "source_name": "EPIC 제공 자료",
            "source_data_sha256": "a" * 64,
            "source_filename": aliases[0]["filename"],
            "source_aliases": aliases,
            "series": [{
                "series_key": "epic.sample_monthly_revenue.m01",
                "label": "예시 매출액",
                "unit": "백만원",
                "frequency": "monthly",
                "aggregation": "sum",
                "points": [{"date": "2026-07-01", "value": value}],
            }],
        }],
    }


def _write_payload(tmp_path, payload):
    path = tmp_path / "epic.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_real_epic_manifest_is_complete_and_deduplicated():
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    datasets = payload["datasets"]
    assert payload["source_file_count"] == 52
    assert payload["unique_dataset_count"] == len(datasets) == 38
    assert sum(len(dataset["source_aliases"]) for dataset in datasets) == 52
    assert sum(len(dataset["series"]) for dataset in datasets) == 261
    assert sum(
        len(series["points"])
        for dataset in datasets
        for series in dataset["series"]
    ) == 19789
    by_id = {dataset["dataset_id"]: dataset for dataset in datasets}
    assert len(by_id["lvs_quarterly_revenue"]["source_aliases"]) == 11
    assert len(by_id["mgm_quarterly_revenue"]["source_aliases"]) == 5
    assert by_id["paradise_monthly_revenue"]["series"][0]["unit"] == "백만원"


def test_import_is_idempotent_and_updates_existing_observation(tmp_path):
    database = tmp_path / "dashboard.db"
    data_file = _write_payload(tmp_path, _payload(value=10))
    first = import_epic_data(database, data_file)
    assert first["series_count"] == 1
    assert first["point_count"] == 1
    assert first["integrity"] == "ok"

    updated = _payload(value=25.5)
    data_file = _write_payload(tmp_path, updated)
    second = import_epic_data(database, data_file)
    assert second["integrity"] == "ok"

    connection = schema.connect(str(database))
    try:
        series = connection.execute(
            "SELECT * FROM source_data_series WHERE series_key=?",
            ("epic.sample_monthly_revenue.m01",),
        ).fetchone()
        points = connection.execute(
            "SELECT observation_date, value FROM source_data_points WHERE series_key=?",
            ("epic.sample_monthly_revenue.m01",),
        ).fetchall()
        state = connection.execute(
            "SELECT state_value FROM source_data_repository_state WHERE state_key=?",
            (STATE_KEY,),
        ).fetchone()
        assert series["category"] == "테스트"
        assert series["is_internal"] == 0
        assert [(row["observation_date"], row["value"]) for row in points] == [
            ("2026-07-01", 25.5)
        ]
        assert json.loads(state["state_value"])["source_file_count"] == 52
    finally:
        connection.close()


@pytest.mark.parametrize("mutation", ["duplicate_date", "non_finite", "bad_frequency"])
def test_invalid_payload_is_rejected_before_database_write(tmp_path, mutation):
    payload = _payload()
    series = payload["datasets"][0]["series"][0]
    if mutation == "duplicate_date":
        series["points"].append(copy.deepcopy(series["points"][0]))
    elif mutation == "non_finite":
        series["points"][0]["value"] = float("inf")
    else:
        series["frequency"] = "weekly"
    data_file = _write_payload(tmp_path, payload)
    database = tmp_path / "dashboard.db"
    with pytest.raises(ValueError):
        import_epic_data(database, data_file)
    if database.exists():
        connection = schema.connect(str(database))
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM source_data_series WHERE series_key LIKE 'epic.%'"
            ).fetchone()[0]
            assert count == 0
        finally:
            connection.close()
