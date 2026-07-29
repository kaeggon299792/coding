"""Telegram notification sender with bounded retries."""

import logging
import time

import requests

import config

logger = logging.getLogger("dashboard")
_API_BASE = "https://api.telegram.org"


def send_alert(text: str, force: bool = False) -> bool:
    if config.TELEGRAM_ALERT_DRY_RUN and not force:
        logger.info("[TELEGRAM_ALERT_DRY_RUN] 전송 예정 메시지:\n%s", text)
        return True

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("텔레그램 설정이 없어 알림을 보낼 수 없습니다.")
        return False

    url = f"{_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(3):
        try:
            response = requests.post(
                url, data=payload, timeout=config.TELEGRAM_REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code == 200:
                return True
            logger.error("긴급 알림 전송 실패: HTTP %s", response.status_code)
            if response.status_code < 500 and response.status_code != 429:
                return False
        except requests.RequestException as error:
            logger.error("긴급 알림 전송 실패: %s", type(error).__name__)
        if attempt < 2:
            time.sleep(0.5 * (2 ** attempt))
    return False
