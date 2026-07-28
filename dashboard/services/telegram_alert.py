"""
대시보드가 새로 추가하는 유일한 "발송" 경로: 중요 공시/법령변경 긴급 알림.

기존 세 프로그램(casino_news_watch/email_monitor/datalab_capture)의 발송
로직과는 완전히 분리된 별도 함수다. TELEGRAM_ALERT_DRY_RUN=true(기본값)이면
실제로 보내지 않고 로그만 남긴다 - 반드시 이 상태로 먼저 검증한 뒤 전환할 것.
"""

import logging

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
    try:
        response = requests.post(url, data=payload, timeout=config.TELEGRAM_REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        logger.error("긴급 알림 전송 실패: %s", type(error).__name__)
        return False

    if response.status_code != 200:
        logger.error("긴급 알림 전송 실패: HTTP %s", response.status_code)
        return False
    return True
