import logging

import pymysql
import requests

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_db_connection():
    return pymysql.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def call_external_api():
    headers = {"Authorization": f"Bearer {config.API_KEY}"}
    response = requests.get("https://api.example.com/status", headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def main():
    logger.info("작업을 시작합니다.")
    # 예시: DB 조회
    # with get_db_connection() as conn:
    #     with conn.cursor() as cursor:
    #         cursor.execute("SELECT 1")
    #         logger.info(cursor.fetchone())

    # 예시: 외부 API 호출
    # logger.info(call_external_api())

    logger.info("작업을 완료했습니다.")


if __name__ == "__main__":
    main()
