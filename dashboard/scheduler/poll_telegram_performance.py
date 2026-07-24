"""
PythonAnywhere Always-on Task 진입점.

텔레그램 getUpdates를 주기적으로 폴링해 데이터랩 실적 메시지를 수집한다.
casino_news_watch/email_monitor의 run_forever.py와 동일한 설계: 처리 중 예외가
나도 프로세스는 죽지 않고 다음 주기에 다시 시도한다.

PythonAnywhere 등록 예시:
  python3 /home/사용자명/coding/dashboard/scheduler/poll_telegram_performance.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import telegram_ingest  # noqa: E402
from utils import setup_logger  # noqa: E402

logger = setup_logger("telegram_ingest")


def main():
    try:
        config.validate_environment()
    except config.ConfigError as error:
        logger.critical("환경변수 설정 오류로 실행할 수 없습니다: %s", error)
        return

    logger.info("텔레그램 실적 수집 상시 폴링을 시작합니다 (간격 %d초).", config.TELEGRAM_POLL_INTERVAL_SECONDS)

    while True:
        try:
            connection = dashboard_db()
            try:
                telegram_ingest.poll_once(connection)
            finally:
                connection.close()
        except Exception as error:  # 예외가 나도 프로세스를 죽이지 않고 다음 주기에 재시도
            logger.error("폴링 주기 중 예기치 않은 오류: %s", error)

        time.sleep(config.TELEGRAM_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
