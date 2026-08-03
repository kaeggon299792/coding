"""
텔레그램 Bot API의 getUpdates(폴링)로 데이터랩 실적 메시지를 수집한다.

기존 casino_news_watch/email_monitor/datalab_capture.py가 쓰는 것과 같은 봇을
"발송(sendMessage/sendPhoto)"이 아니라 "수신(getUpdates)" 용도로만 사용한다.
이 모듈은 텔레그램에 어떤 메시지도 보내지 않는다 — 발송 로직과 완전히 분리되어
있어 기존 세 프로그램과 충돌하지 않는다(사용자 확인: 지금까지 getUpdates를
쓰는 다른 프로그램 없음).

getUpdates는 폴링을 시작한 시점 이후의 메시지만 가져올 수 있다(텔레그램이
과거 이력을 영구 보관하지 않음) - 이 점은 README에도 명시한다.
"""

import datetime
import logging

import requests

import config
from dashboard_db import queries
from services import performance_parser

logger = logging.getLogger("telegram_ingest")

_API_BASE = "https://api.telegram.org"
_webhook_verified = False


class TelegramIngestError(Exception):
    pass


def _api_url(method):
    return f"{_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def check_no_webhook_conflict():
    """getUpdates를 쓰기 전에 webhook이 설정돼 있지 않은지 확인한다.

    webhook이 설정된 상태에서 getUpdates를 호출하면 텔레그램이 거부하거나
    빈 결과만 준다 - 원인 파악이 쉽도록 명시적으로 먼저 확인한다.
    """
    try:
        response = requests.get(_api_url("getWebhookInfo"), timeout=config.TELEGRAM_REQUEST_TIMEOUT_SECONDS)
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        logger.error("getWebhookInfo 호출 실패: %s", type(error).__name__)
        return False, "webhook 상태를 확인할 수 없습니다."

    if not data.get("ok"):
        return False, data.get("description", "알 수 없는 오류")

    webhook_url = (data.get("result") or {}).get("url") or ""
    if webhook_url:
        return False, f"이미 webhook이 설정되어 있어 getUpdates와 충돌합니다: {webhook_url}"
    return True, None


def _get_updates(offset):
    params = {
        "timeout": 25,
        "allowed_updates": '["message","channel_post"]',
    }
    if offset:
        params["offset"] = offset

    response = requests.get(
        _api_url("getUpdates"), params=params, timeout=config.TELEGRAM_REQUEST_TIMEOUT_SECONDS
    )
    data = response.json()
    if not data.get("ok"):
        raise TelegramIngestError(data.get("description", "getUpdates 오류"))
    return data.get("result", [])


def _report_date_from_unix(unix_ts):
    dt = datetime.datetime.fromtimestamp(unix_ts, tz=config.KST)
    return dt.strftime("%Y-%m-%d"), dt.isoformat()


def _extract_text_and_kind(message):
    """메시지에서 (message_kind, text) 를 뽑는다. 사진 캡션과 순수 텍스트를 모두 다룬다."""
    if message.get("photo") and message.get("caption"):
        return "photo", message["caption"]
    if message.get("text"):
        return "text", message["text"]
    return None, None


def poll_once(dashboard_connection):
    """한 번의 폴링 주기를 실행한다. 새로 저장한 실적 리포트 수를 반환한다."""

    global _webhook_verified
    if not _webhook_verified:
        ok, reason = check_no_webhook_conflict()
        if not ok:
            logger.error("텔레그램 폴링을 건너뜁니다: %s", reason)
            queries.log_error(
                dashboard_connection,
                "telegram_ingest",
                "webhook_conflict",
                reason or "",
            )
            return 0
        _webhook_verified = True

    last_update_id = queries.get_last_update_id(dashboard_connection)
    offset = last_update_id + 1 if last_update_id else None

    try:
        updates = _get_updates(offset)
    except (requests.RequestException, TelegramIngestError) as error:
        # requests exceptions may include the request URL, and Telegram embeds
        # the bot token in that URL. Persist only the exception class.
        logger.error("getUpdates 호출 실패: %s", type(error).__name__)
        queries.log_error(
            dashboard_connection, "telegram_ingest", type(error).__name__,
            "Telegram Bot API request failed",
        )
        return 0

    saved_count = 0
    max_update_id = last_update_id

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None:
            max_update_id = max(max_update_id, update_id)

        message = update.get("message") or update.get("channel_post")
        if not message:
            continue

        chat_id = str((message.get("chat") or {}).get("id") or "")
        if config.TELEGRAM_CHAT_ID and chat_id != str(config.TELEGRAM_CHAT_ID):
            continue

        message_kind, text = _extract_text_and_kind(message)
        if not text:
            continue

        header_type = performance_parser.detect_header_type(text)
        if header_type is None:
            # 데이터랩 실적 메시지가 아님(뉴스/이메일 알림 등 같은 챗의 다른 메시지) - 저장하지 않는다.
            continue

        parsed, parse_error = performance_parser.parse(text)
        report_date, received_at = _report_date_from_unix(message.get("date"))

        queries.save_performance_report(
            dashboard_connection,
            report_date=report_date,
            telegram_update_id=update_id,
            telegram_message_id=message.get("message_id"),
            telegram_chat_id=chat_id,
            message_kind=message_kind,
            header_type=header_type,
            raw_text=text,
            parsed_data=(parsed.fields if parsed else None),
            parsing_status=("ok" if parsed else "failed"),
            parsing_error=parse_error,
            received_at=received_at,
        )
        saved_count += 1

    if max_update_id != last_update_id:
        queries.set_last_update_id(dashboard_connection, max_update_id)

    if saved_count:
        logger.info("실적 메시지 %d건 저장 완료", saved_count)

    return saved_count
