"""Import Paradise monthly VIP visiting-day totals into the central repository."""

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

STATE_KEY = "paradise_vip_visits_import_v1"


def _validate(payload):
    required = (
        "series_key", "category", "label", "unit", "frequency",
        "aggregation", "source_name", "source_sha256", "points",
    )
    if payload.get("schema_version") != 1 or any(not payload.get(key) for key in required):
        raise ValueError("파라다이스 VIP 방문일 데이터 형식이 올바르지 않습니다.")
    if payload["frequency"] != "monthly" or payload["aggregation"] != "sum":
        raise ValueError("월별 합계 데이터만 가져올 수 있습니다.")
    if len(payload["source_sha256"]) != 64:
        raise ValueError("원본 파일 체크섬이 올바르지 않습니다.")
    seen = set()
    for point in payload["points"]:
        observed = point.get("date")
        try:
            date.fromisoformat(observed)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"관측일이 올바르지 않습니다: {observed}") from exc
        value = point.get("value")
        if observed in seen or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"방문일 값이 올바르지 않습니다: {observed}")
        seen.add(observed)
    return payload


def import_paradise_vip_visits(database_path, data_path):
    raw = Path(data_path).read_bytes()
    payload = _validate(json.loads(raw.decode("utf-8")))
    connection = schema.connect(str(database_path))
    try:
        connection.execute("BEGIN IMMEDIATE")
        queries.upsert_source_data_series(
            connection,
            series_key=payload["series_key"],
            category=payload["category"],
            label=payload["label"],
            unit=payload["unit"],
            frequency=payload["frequency"],
            aggregation=payload["aggregation"],
            source_name=payload["source_name"],
            source_url=None,
            is_internal=False,
        )
        source_prefix = payload["source_sha256"][:16]
        for point in payload["points"]:
            queries.upsert_source_data_point(
                connection,
                series_key=payload["series_key"],
                observation_date=point["date"],
                value=point["value"],
                source_record_key=f"{source_prefix}:{point['date']}",
            )
        state = {
            "generated_on": payload.get("generated_on"),
            "source_filename": payload.get("source_filename"),
            "source_sha256": payload["source_sha256"],
            "series_key": payload["series_key"],
            "point_count": len(payload["points"]),
            "data_sha256": hashlib.sha256(raw).hexdigest(),
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
    print(json.dumps(
        import_paradise_vip_visits(args.database, args.data_file),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
