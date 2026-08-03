"""Hourly-safe LMS inventory sync; does not call any translation API."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_db import schema
from services.localization_management import scan_project


if __name__ == "__main__":
    connection = schema.connect()
    try:
        print(json.dumps(scan_project(connection, PROJECT_ROOT), ensure_ascii=False))
    finally:
        connection.close()
