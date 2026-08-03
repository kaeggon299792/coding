"""기존 숫자 원본을 통합 누적 저장소에 멱등 동기화한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import dashboard_db  # noqa: E402
from services import source_data_repository  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("source_data_repository_sync")


def run():
    connection = dashboard_db()
    try:
        source_data_repository.synchronize_existing_data(connection, force=True)
        stats = source_data_repository.queries.source_data_repository_stats(
            connection, include_internal=True
        )
        logger.info(
            "통합 숫자 저장소 동기화 완료: 데이터 종류 %s개, 누적값 %s개",
            stats.get("series_count", 0), stats.get("point_count", 0),
        )
        return stats
    finally:
        connection.close()


if __name__ == "__main__":
    run()
