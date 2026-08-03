"""PythonAnywhere scheduled task for Macau/Japan casino-news collection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import dashboard_db  # noqa: E402
from services import overseas_news  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("overseas_news_sync")


def run():
    connection = dashboard_db()
    try:
        summary = overseas_news.sync(connection)
        logger.info(
            "해외 뉴스 동기화 완료: 신규 %d건, OpenAI 일괄 분석 %d건, 상태 %s",
            summary["inserted"],
            summary["translated"],
            summary["status"],
        )
        for error in summary["errors"]:
            logger.warning("해외 뉴스 동기화 부분 오류: %s", error)
    finally:
        connection.close()


if __name__ == "__main__":
    run()
