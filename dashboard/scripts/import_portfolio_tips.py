"""Safely migrate portfolio static/data/tips.json into dashboard.db."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard_db import schema
from services import tips_content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--db")
    parser.add_argument("--author-id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = Path(args.source)
    records = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("source JSON must be an array")
    if not args.apply:
        print(f"DRY RUN: {len(records)} records validated; add --apply to migrate")
        return
    connection = schema.connect(args.db)
    try:
        inserted, skipped = tips_content.import_portfolio_records(
            connection, records, args.author_id
        )
        print(f"Migration complete: inserted={inserted}, skipped={skipped}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
