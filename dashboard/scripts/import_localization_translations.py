"""Import a reviewed localization CSV into the dashboard SQLite database."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_db import schema
from services import localization_management


class FileUpload:
    def __init__(self, path):
        self.path = Path(path)
        self.filename = self.path.name

    def read(self, size=-1):
        with self.path.open("rb") as stream:
            return stream.read(size)


def import_translations(database_path, csv_path, language_code):
    if language_code not in {"en", "ja", "yue-HK"}:
        raise ValueError(f"Unsupported language code: {language_code}")

    connection = schema.connect(str(database_path))
    try:
        language = connection.execute(
            "SELECT 1 FROM localization_languages WHERE language_code=? AND is_active=1",
            (language_code,),
        ).fetchone()
        if language is None:
            raise ValueError(f"Inactive or unknown language code: {language_code}")

        result = localization_management.import_file(
            connection, FileUpload(csv_path), language_code
        )
        if result["errors"]:
            raise RuntimeError(
                f"Localization import rejected {result['errors']} row(s); restore the database backup."
            )

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        completed = connection.execute(
            """
            SELECT COUNT(*)
              FROM localization_translations
             WHERE language_code=? AND status='Completed'
            """,
            (language_code,),
        ).fetchone()[0]
        return {**result, "language_code": language_code, "completed": completed,
                "integrity": integrity}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--language", required=True, choices=("en", "ja", "yue-HK"))
    args = parser.parse_args()
    print(json.dumps(
        import_translations(args.database, args.csv_file, args.language),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
