"""Hourly-safe LMS inventory sync; does not call any translation API."""

import json
from pathlib import Path

from dashboard_db import schema
from services.localization_management import scan_project


if __name__ == "__main__":
    connection = schema.connect()
    try:
        print(json.dumps(scan_project(connection, Path(__file__).resolve().parents[1]), ensure_ascii=False))
    finally:
        connection.close()
