"""회사 대표자 공개 프로필을 중앙 SQLite DB에 멱등 반영한다."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_db import schema


def import_profiles(database_path, data_path):
    payload = json.loads(Path(data_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("profiles"), list):
        raise ValueError("지원하지 않는 대표자 프로필 데이터 스키마입니다.")
    profiles = payload["profiles"]
    imported_at = datetime.now(timezone.utc).isoformat()
    connection = schema.connect(str(database_path))
    try:
        connection.execute("BEGIN IMMEDIATE")
        for item in profiles:
            if not all(item.get(key) for key in (
                "company_name", "profile_as_of", "executive_name", "title", "source_label"
            )):
                raise ValueError(f"필수 대표자 프로필 값이 없습니다: {item}")
            connection.execute(
                """
                INSERT INTO company_executive_profiles (
                    company_name, profile_as_of, executive_name, title,
                    appointed_on, workplace_address, birth_date, high_school,
                    university, major, source_label, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_name, profile_as_of, executive_name, title)
                DO UPDATE SET
                    appointed_on=excluded.appointed_on,
                    workplace_address=excluded.workplace_address,
                    birth_date=excluded.birth_date,
                    high_school=excluded.high_school,
                    university=excluded.university,
                    major=excluded.major,
                    source_label=excluded.source_label,
                    imported_at=excluded.imported_at
                """,
                (
                    item["company_name"], item["profile_as_of"],
                    item["executive_name"], item["title"], item.get("appointed_on"),
                    item.get("workplace_address"), item.get("birth_date"),
                    item.get("high_school"), item.get("university"), item.get("major"),
                    item["source_label"], imported_at,
                ),
            )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check 실패: {integrity}")
        return {
            "companies": len({item["company_name"] for item in profiles}),
            "profiles": connection.execute(
                "SELECT COUNT(*) FROM company_executive_profiles"
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
        import_profiles(args.database, args.data_file), ensure_ascii=False, indent=2
    ))


if __name__ == "__main__":
    main()
