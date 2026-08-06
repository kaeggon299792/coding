"""Import normalized EPIC casino-industry workbooks into the central SQLite DB."""

import argparse
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_db import queries, schema

ALLOWED_FREQUENCIES = {"monthly", "quarterly", "yearly"}
ALLOWED_AGGREGATIONS = {"sum", "avg", "last"}
STATE_KEY = "epic_industry_metrics_import_v1"


def _validate_payload(payload):
    if payload.get("schema_version") != 1:
        raise ValueError("지원하지 않는 EPIC 데이터 스키마입니다.")
    if payload.get("source_file_count") != 52:
        raise ValueError("EPIC 원본 파일 수가 52개가 아닙니다.")
    datasets = payload.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("가져올 EPIC 데이터셋이 없습니다.")
    if payload.get("unique_dataset_count") != len(datasets):
        raise ValueError("고유 데이터셋 수가 일치하지 않습니다.")

    dataset_ids = set()
    series_keys = set()
    alias_names = set()
    point_count = 0
    for dataset in datasets:
        dataset_id = dataset.get("dataset_id")
        if not dataset_id or dataset_id in dataset_ids:
            raise ValueError(f"데이터셋 ID가 비어 있거나 중복됩니다: {dataset_id}")
        dataset_ids.add(dataset_id)
        if not dataset.get("category") or not dataset.get("label"):
            raise ValueError(f"데이터셋 메타데이터가 비어 있습니다: {dataset_id}")
        aliases = dataset.get("source_aliases")
        if not isinstance(aliases, list) or not aliases:
            raise ValueError(f"출처 파일 이력이 없습니다: {dataset_id}")
        for alias in aliases:
            filename = alias.get("filename")
            digest = alias.get("sha256")
            if not filename or filename in alias_names or not digest or len(digest) != 64:
                raise ValueError(f"출처 파일 이력이 잘못되었습니다: {filename}")
            alias_names.add(filename)

        series_list = dataset.get("series")
        if not isinstance(series_list, list) or not series_list:
            raise ValueError(f"시계열이 없습니다: {dataset_id}")
        for series in series_list:
            key = series.get("series_key")
            frequency = series.get("frequency")
            aggregation = series.get("aggregation")
            if not key or key in series_keys:
                raise ValueError(f"시계열 키가 비어 있거나 중복됩니다: {key}")
            if not key.startswith(f"epic.{dataset_id}."):
                raise ValueError(f"시계열 키와 데이터셋 ID가 일치하지 않습니다: {key}")
            if frequency not in ALLOWED_FREQUENCIES:
                raise ValueError(f"지원하지 않는 주기입니다: {frequency}")
            if aggregation not in ALLOWED_AGGREGATIONS:
                raise ValueError(f"지원하지 않는 집계 방식입니다: {aggregation}")
            if not series.get("label") or not series.get("unit"):
                raise ValueError(f"시계열 메타데이터가 비어 있습니다: {key}")
            series_keys.add(key)
            seen_dates = set()
            points = series.get("points")
            if not isinstance(points, list) or not points:
                raise ValueError(f"관측값이 없습니다: {key}")
            for point in points:
                date_text = point.get("date")
                try:
                    date.fromisoformat(date_text)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"관측일이 잘못되었습니다: {key} {date_text}") from exc
                if date_text in seen_dates:
                    raise ValueError(f"관측일이 중복됩니다: {key} {date_text}")
                seen_dates.add(date_text)
                value = point.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"관측값이 유한 숫자가 아닙니다: {key} {date_text}")
                point_count += 1

    if len(alias_names) != payload["source_file_count"]:
        raise ValueError("출처 파일 이력 수가 원본 파일 수와 다릅니다.")
    return datasets, len(series_keys), point_count


def import_epic_data(database_path, data_path):
    data_path = Path(data_path)
    raw_data = data_path.read_bytes()
    payload = json.loads(raw_data.decode("utf-8"))
    datasets, series_count, point_count = _validate_payload(payload)
    data_digest = hashlib.sha256(raw_data).hexdigest()
    connection = schema.connect(str(database_path))
    try:
        connection.execute("BEGIN IMMEDIATE")
        for dataset in datasets:
            source_digest = dataset["source_data_sha256"]
            for series in dataset["series"]:
                queries.upsert_source_data_series(
                    connection,
                    series_key=series["series_key"],
                    category=dataset["category"],
                    label=series["label"],
                    unit=series["unit"],
                    frequency=series["frequency"],
                    aggregation=series["aggregation"],
                    source_name=dataset.get("source_name") or "EPIC 제공 자료",
                    source_url=None,
                    is_internal=False,
                )
                for point in series["points"]:
                    queries.upsert_source_data_point(
                        connection,
                        series_key=series["series_key"],
                        observation_date=point["date"],
                        value=point["value"],
                        source_record_key=f"{source_digest[:16]}:{point['date']}",
                    )
        state = {
            "schema_version": payload["schema_version"],
            "generated_on": payload.get("generated_on"),
            "source_file_count": payload["source_file_count"],
            "dataset_count": len(datasets),
            "series_count": series_count,
            "point_count": point_count,
            "data_sha256": data_digest,
        }
        queries.set_source_data_repository_state(
            connection, STATE_KEY, json.dumps(state, ensure_ascii=False, sort_keys=True)
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check 실패: {integrity}")
        return {**state, "integrity": integrity}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_file", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_epic_data(args.database, args.data_file), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
