"""회사 신용평가 이력을 중앙 SQLite DB에 멱등 반영한다."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_db import schema


def import_ratings(database_path, data_path):
    payload = json.loads(Path(data_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("ratings"), list):
        raise ValueError("지원하지 않는 신용평가 데이터 스키마입니다.")
    ratings = payload["ratings"]
    imported_at = datetime.now(timezone.utc).isoformat()
    connection = schema.connect(str(database_path))
    try:
        connection.execute("BEGIN IMMEDIATE")
        for item in ratings:
            if not all(item.get(key) for key in (
                "company_name", "rating", "evaluated_on", "rating_type",
                "agency", "source_label",
            )):
                raise ValueError(f"필수 신용평가 값이 없습니다: {item}")
            connection.execute(
                """
                INSERT OR IGNORE INTO company_credit_ratings (
                    company_name, rating, evaluated_on, financial_as_of,
                    rating_type, agency, source_label, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["company_name"], item["rating"], item["evaluated_on"],
                    item.get("financial_as_of"), item["rating_type"], item["agency"],
                    item["source_label"], imported_at,
                ),
            )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check 실패: {integrity}")
        return {
            "companies": len({item["company_name"] for item in ratings}),
            "ratings": connection.execute(
                "SELECT COUNT(1) FROM company_credit_ratings"
            ).fetchone()[0],
            "integrity": integrity,
        }
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
        import_ratings(args.database, args.data_file), ensure_ascii=False, indent=2
    ))


if __name__ == "__main__":
    main()
