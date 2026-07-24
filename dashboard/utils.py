"""
공통 유틸리티: 시간대 처리, 로그 마스킹, 해시.

기존 casino_news_watch/utils.py, email_monitor/utils.py의 패턴을 그대로 재사용한다.
"""

import hashlib
import html
import logging
from datetime import datetime

import config

_MASK = "***MASKED***"


def now_kst() -> datetime:
    return datetime.now(config.KST)


def today_kst_str() -> str:
    return now_kst().strftime("%Y-%m-%d")


def escape_html(text) -> str:
    return html.escape(text or "", quote=False)


def sha256_of(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class SecretMaskingFilter(logging.Filter):
    """로그 메시지에서 알려진 비밀값을 자동으로 마스킹한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True

        secrets = [s for s in config.known_secrets() if s]
        if not secrets:
            return True

        masked = message
        for secret in secrets:
            if secret and secret in masked:
                masked = masked.replace(secret, _MASK)

        if masked != message:
            record.msg = masked
            record.args = ()

        return True


def setup_logger(name: str) -> logging.Logger:
    """날짜별 로그 파일 + 콘솔 출력, 비밀값 자동 마스킹이 적용된 로거를 만든다."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / f"{name}.log",
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretMaskingFilter())
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SecretMaskingFilter())
    logger.addHandler(console_handler)

    return logger
