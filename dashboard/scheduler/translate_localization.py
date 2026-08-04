"""PythonAnywhere daily task: translate pending Japanese and Cantonese strings."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from extensions import dashboard_db  # noqa: E402
from services.localization_auto_translation import run_daily  # noqa: E402
from utils import setup_logger  # noqa: E402


logger = setup_logger("localization_translation")


def run():
    connection = dashboard_db()
    try:
        summary = run_daily(connection, PROJECT_ROOT)
        logger.info("자동 번역 완료: %s", json.dumps(summary, ensure_ascii=False))
        return summary
    except Exception:
        logger.exception("자동 번역 배치 실패")
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    run()
