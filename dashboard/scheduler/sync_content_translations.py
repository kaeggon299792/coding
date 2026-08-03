"""PythonAnywhere daily task for cached English public content."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard_db.schema import connect
from services.content_translation import run_daily_translation


def main():
    connection = connect()
    try:
        print(json.dumps(run_daily_translation(connection), ensure_ascii=False))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
