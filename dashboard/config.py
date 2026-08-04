"""
환경변수와 전역 설정을 모아두는 모듈.

기존 casino_news_watch/config.py, email_monitor/config.py와 동일한 스타일을
따른다: 모든 값은 .env(python-dotenv)로 덮어쓸 수 있고, 비밀값은 절대
기본값으로 하드코딩하지 않는다.
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

KST = ZoneInfo("Asia/Seoul")

load_dotenv(ENV_FILE)


# ============================================================
# 환경변수 파싱 헬퍼 (기존 프로그램들과 동일한 헬퍼를 그대로 재사용)
# ============================================================

def _get_str(name, default=""):
    return os.environ.get(name, default).strip()


def _get_bool(name, default=False):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_int(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _get_optional_float(name):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def _get_float(name, default):
    value = _get_optional_float(name)
    return default if value is None else value


def _get_list(name, default_list=()):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return list(default_list)
    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


# ============================================================
# 대시보드 자체 DB 및 뉴스 프로그램의 읽기 전용 DB 경로
# ============================================================
# 기존 뉴스 프로그램의 DB는 절대 쓰기 접근하지 않는다(읽기 전용 연결만 사용).
# 경로는 PythonAnywhere 배포 환경에 맞춰 .env에서 절대경로로 지정한다.

DASHBOARD_DB_FILE = _get_str("DASHBOARD_DB_FILE", str(BASE_DIR / "dashboard.db"))
NEWS_DB_FILE = _get_str("NEWS_DB_FILE", "")  # 예: /home/사용자명/casino_news_watch/news_history.db
RESEARCH_LIBRARY_DIR = _get_str(
    "RESEARCH_LIBRARY_DIR", str(BASE_DIR / "data" / "research_library")
)
RESEARCH_MAX_FILE_BYTES = _get_int("RESEARCH_MAX_FILE_BYTES", 20 * 1024 * 1024)
RESEARCH_MAX_PDF_PAGES = _get_int("RESEARCH_MAX_PDF_PAGES", 250)
RESEARCH_MAX_EXTRACTED_CHARS = _get_int("RESEARCH_MAX_EXTRACTED_CHARS", 160_000)
OFFICIAL_DOC_TEMP_DIR = _get_str(
    "OFFICIAL_DOC_TEMP_DIR", str(BASE_DIR / "data" / "official_doc_temp")
)
OFFICIAL_DOC_MAX_UPLOAD_MB = _get_int("OFFICIAL_DOC_MAX_UPLOAD_MB", 50)
TIPS_ATTACHMENT_DIR = _get_str(
    "TIPS_ATTACHMENT_DIR", str(BASE_DIR / "data" / "tip_attachments")
)
TIPS_MAX_ATTACHMENT_BYTES = _get_int(
    "TIPS_MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024
)
OFFICIAL_DOC_TEMP_RETENTION_DAYS = _get_int("OFFICIAL_DOC_TEMP_RETENTION_DAYS", 3)
SYNC_CLAIM_TIMEOUT_MINUTES = _get_int("SYNC_CLAIM_TIMEOUT_MINUTES", 30)
SYNC_API_TOKEN = _get_str("SYNC_API_TOKEN")


# ============================================================
# 텔레그램 (기존 세 프로그램과 동일한 봇 재사용, 발송이 아닌 getUpdates 수신 전용)
# ============================================================

TELEGRAM_BOT_TOKEN = _get_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get_str("TELEGRAM_CHAT_ID")

# 대시보드가 새로 "발송"하는 유일한 경로(중요 공시 긴급 알림). 발송 전용 함수와
# 완전히 분리되어 있으며, 기존 세 프로그램의 발송 로직과는 무관하다.
TELEGRAM_ALERT_DRY_RUN = _get_bool("TELEGRAM_ALERT_DRY_RUN", True)

TELEGRAM_POLL_INTERVAL_SECONDS = _get_int("TELEGRAM_POLL_INTERVAL_SECONDS", 60)
TELEGRAM_REQUEST_TIMEOUT_SECONDS = _get_int("TELEGRAM_REQUEST_TIMEOUT_SECONDS", 35)


# ============================================================
# OpenAI (경영진 시사점 / 공시 분석 / 법률 분석 공통)
# ============================================================

OPENAI_API_KEY = _get_str("OPENAI_API_KEY")
OPENAI_INSIGHT_MODEL = _get_str("OPENAI_INSIGHT_MODEL")

OPENAI_INPUT_COST_PER_1M = _get_optional_float("OPENAI_INPUT_COST_PER_1M")
OPENAI_OUTPUT_COST_PER_1M = _get_optional_float("OPENAI_OUTPUT_COST_PER_1M")

# UI localization uses a smaller dedicated model so that the daily executive
# analysis model can remain independent and translation costs stay predictable.
OPENAI_TRANSLATION_MODEL = _get_str("OPENAI_TRANSLATION_MODEL", "gpt-5.4-mini")
OPENAI_TRANSLATION_INPUT_COST_PER_1M = _get_float(
    "OPENAI_TRANSLATION_INPUT_COST_PER_1M", 0.75
)
OPENAI_TRANSLATION_OUTPUT_COST_PER_1M = _get_float(
    "OPENAI_TRANSLATION_OUTPUT_COST_PER_1M", 4.50
)
LOCALIZATION_TRANSLATION_BATCH_SIZE = _get_int(
    "LOCALIZATION_TRANSLATION_BATCH_SIZE", 40
)
LOCALIZATION_TRANSLATION_MAX_ITEMS_PER_RUN = _get_int(
    "LOCALIZATION_TRANSLATION_MAX_ITEMS_PER_RUN", 1000
)
LOCALIZATION_TRANSLATION_MAX_CHARS_PER_BATCH = _get_int(
    "LOCALIZATION_TRANSLATION_MAX_CHARS_PER_BATCH", 12000
)
LOCALIZATION_TRANSLATION_LANGUAGES = _get_str(
    "LOCALIZATION_TRANSLATION_LANGUAGES", "ja,yue-HK"
)

OPENAI_REQUEST_TIMEOUT_SECONDS = _get_int("OPENAI_REQUEST_TIMEOUT_SECONDS", 60)
OPENAI_MAX_RETRIES = _get_int("OPENAI_MAX_RETRIES", 2)

# 해외뉴스는 RSS를 저비용 모델로 묶어서 분석하고, 중요한 기사만 웹 검색한다.
OPENAI_NEWS_MODEL = _get_str("OPENAI_NEWS_MODEL", "gpt-5-mini")
OPENAI_NEWS_MAX_PER_RUN = _get_int("OPENAI_NEWS_MAX_PER_RUN", 30)
OPENAI_NEWS_BATCH_SIZE = _get_int("OPENAI_NEWS_BATCH_SIZE", 10)
OPENAI_NEWS_WEB_MAX_PER_RUN = _get_int("OPENAI_NEWS_WEB_MAX_PER_RUN", 3)
OPENAI_NEWS_WEB_IMPORTANCE_THRESHOLD = _get_int(
    "OPENAI_NEWS_WEB_IMPORTANCE_THRESHOLD", 75
)
OPENAI_NEWS_INPUT_COST_PER_1M = _get_float("OPENAI_NEWS_INPUT_COST_PER_1M", 0.25)
OPENAI_NEWS_OUTPUT_COST_PER_1M = _get_float("OPENAI_NEWS_OUTPUT_COST_PER_1M", 2.00)
OPENAI_NEWS_WEB_SEARCH_COST_PER_CALL = _get_float(
    "OPENAI_NEWS_WEB_SEARCH_COST_PER_CALL", 0.01
)

MAX_GPT_CALLS_PER_DAY = _get_int("MAX_GPT_CALLS_PER_DAY", 50)
DAILY_OPENAI_BUDGET_USD = _get_float("DAILY_OPENAI_BUDGET_USD", 0.50)

AI_INSIGHT_PROMPT_VERSION = _get_str("AI_INSIGHT_PROMPT_VERSION", "exec-insight-v1")
AI_DISCLOSURE_PROMPT_VERSION = _get_str("AI_DISCLOSURE_PROMPT_VERSION", "dart-summary-v1")
AI_LAW_PROMPT_VERSION = _get_str("AI_LAW_PROMPT_VERSION", "law-summary-v1")
CONTENT_TRANSLATION_BATCH_SIZE = _get_int("CONTENT_TRANSLATION_BATCH_SIZE", 20)
CONTENT_TRANSLATION_MAX_ITEMS_PER_RUN = _get_int("CONTENT_TRANSLATION_MAX_ITEMS_PER_RUN", 100)
CONTENT_TRANSLATION_MAX_CHARS_PER_BATCH = _get_int("CONTENT_TRANSLATION_MAX_CHARS_PER_BATCH", 24000)
CONTENT_TRANSLATION_NEWS_DAYS = _get_int("CONTENT_TRANSLATION_NEWS_DAYS", 30)
CONTENT_TRANSLATION_NEWS_SCAN_LIMIT = _get_int("CONTENT_TRANSLATION_NEWS_SCAN_LIMIT", 500)

# Gemini overseas-news grounding. The API key must stay in the server-side .env.
GEMINI_API_KEY = _get_str("GEMINI_API_KEY")
GEMINI_MODEL = _get_str("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_REQUEST_TIMEOUT_SECONDS = _get_int("GEMINI_REQUEST_TIMEOUT_SECONDS", 90)
GEMINI_MAX_RETRIES = _get_int("GEMINI_MAX_RETRIES", 2)
GEMINI_NEWS_MAX_PER_RUN = _get_int("GEMINI_NEWS_MAX_PER_RUN", 30)
GEMINI_INPUT_COST_PER_1M_USD = _get_float("GEMINI_INPUT_COST_PER_1M_USD", 1.50)
GEMINI_OUTPUT_COST_PER_1M_USD = _get_float("GEMINI_OUTPUT_COST_PER_1M_USD", 9.00)
GEMINI_SEARCH_COST_PER_1000_USD = _get_float(
    "GEMINI_SEARCH_COST_PER_1000_USD", 14.00
)
GEMINI_USD_KRW_FALLBACK_RATE = _get_float("GEMINI_USD_KRW_FALLBACK_RATE", 1400.0)


# ============================================================
# DART 공시통합정보 OpenAPI (opendart.fss.or.kr, 별도 무료 API 키 필요)
# ============================================================

DART_API_KEY = _get_str("DART_API_KEY")
DART_REQUEST_TIMEOUT_SECONDS = _get_int("DART_REQUEST_TIMEOUT_SECONDS", 20)
# corpCode.xml(전체 상장사 목록 zip)은 응답이 커서 더 긴 타임아웃을 둔다.
DART_CORP_CODE_TIMEOUT_SECONDS = _get_int("DART_CORP_CODE_TIMEOUT_SECONDS", 60)
DART_SYNC_LOOKBACK_DAYS = _get_int("DART_SYNC_LOOKBACK_DAYS", 3)

OPINET_API_KEY = _get_str("OPINET_API_KEY")
KOREAEXIM_API_KEY = _get_str("KOREAEXIM_API_KEY")
ECONOMIC_DATA_REQUEST_TIMEOUT_SECONDS = _get_int("ECONOMIC_DATA_REQUEST_TIMEOUT_SECONDS", 20)

# 중요 공시로 간주해 텔레그램 긴급 알림을 보낼 보고서명 키워드
DEFAULT_DART_IMPORTANT_KEYWORDS = [
    "사업보고서", "반기보고서", "분기보고서", "주요사항보고서", "유상증자",
    "무상증자", "회사채", "소송", "제재", "최대주주", "합병", "분할",
    "영업양수", "영업양도", "감사의견", "관리종목", "상장폐지",
]
DART_IMPORTANT_KEYWORDS = _get_list("DART_IMPORTANT_KEYWORDS", DEFAULT_DART_IMPORTANT_KEYWORDS)


# ============================================================
# 국가법령정보센터 Open API (open.law.go.kr, 별도 무료 API 키 필요)
# ============================================================

LAW_API_OC = _get_str("LAW_API_OC")  # 발급받은 기관코드(이메일 아이디 부분)
LAW_API_KEY = _get_str("LAW_API_KEY")
LAW_REQUEST_TIMEOUT_SECONDS = _get_int("LAW_REQUEST_TIMEOUT_SECONDS", 20)

ASSEMBLY_API_KEY = _get_str("ASSEMBLY_API_KEY")
ASSEMBLY_ERA = _get_str("ASSEMBLY_ERA", "제22대")
ASSEMBLY_REQUEST_TIMEOUT_SECONDS = _get_int("ASSEMBLY_REQUEST_TIMEOUT_SECONDS", 20)
ASSEMBLY_AI_MAX_PER_RUN = _get_int("ASSEMBLY_AI_MAX_PER_RUN", 10)
ASSEMBLY_BILL_TEXT_MAX_CHARS = _get_int("ASSEMBLY_BILL_TEXT_MAX_CHARS", 16000)
ASSEMBLY_BILL_KEYWORDS = _get_list(
    "ASSEMBLY_BILL_KEYWORDS",
    ["카지노", "관광진흥법", "복합리조트", "사행산업", "외국인전용카지노"],
)
LAWMAKING_API_OC = _get_str("LAWMAKING_API_OC", "kaegoon")
LAWMAKING_REQUEST_TIMEOUT_SECONDS = _get_int("LAWMAKING_REQUEST_TIMEOUT_SECONDS", 20)
LAWMAKING_NOTICE_KEYWORDS = _get_list(
    "LAWMAKING_NOTICE_KEYWORDS",
    ["카지노", "관광진흥법", "복합리조트", "사행산업", "외국인전용카지노"],
)

MARKET_DATA_API_KEY = _get_str("MARKET_DATA_API_KEY")
MARKET_DATA_REQUEST_TIMEOUT_SECONDS = _get_int("MARKET_DATA_REQUEST_TIMEOUT_SECONDS", 30)
TOSS_INVEST_CLIENT_ID = _get_str("TOSS_INVEST_CLIENT_ID")
TOSS_INVEST_CLIENT_SECRET = _get_str("TOSS_INVEST_CLIENT_SECRET")
SALARY_REQUEST_TIMEOUT_SECONDS = _get_int("SALARY_REQUEST_TIMEOUT_SECONDS", 20)
RECRUITMENT_REQUEST_TIMEOUT_SECONDS = _get_int("RECRUITMENT_REQUEST_TIMEOUT_SECONDS", 20)
RECRUITMENT_AI_MAX_PER_RUN = _get_int("RECRUITMENT_AI_MAX_PER_RUN", 8)

# ============================================================
# 한국문화관광연구원 출입국관광통계 Open API
# ============================================================

TOURISM_API_KEY = _get_str("TOURISM_API_KEY")
TOURISM_REQUEST_TIMEOUT_SECONDS = _get_int("TOURISM_REQUEST_TIMEOUT_SECONDS", 45)

DEFAULT_MONITORED_LAWS = [
    "관광진흥법", "관광진흥법 시행령", "관광진흥법 시행규칙",
    "특정 금융거래정보의 보고 및 이용등에 관한 법률", "외국환거래법",
    "개인정보 보호법", "근로기준법", "산업안전보건법", "중대재해 처벌 등에 관한 법률",
]


# ============================================================
# 인증 / 세션 / CSRF
# ============================================================

FLASK_SECRET_KEY = _get_str("FLASK_SECRET_KEY")
SESSION_LIFETIME_DAYS = _get_int("SESSION_LIFETIME_DAYS", 7)
SESSION_IDLE_MINUTES = _get_int("SESSION_IDLE_MINUTES", 30)
SESSION_ABSOLUTE_HOURS = _get_int("SESSION_ABSOLUTE_HOURS", 8)
REMEMBER_LOGIN_DAYS = _get_int("REMEMBER_LOGIN_DAYS", 30)
PROFILE_IMAGE_MAX_BYTES = _get_int("PROFILE_IMAGE_MAX_BYTES", 3 * 1024 * 1024)
SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", True)
GOOGLE_CLIENT_ID = _get_str("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get_str("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = _get_str("GOOGLE_REDIRECT_URI")
GOOGLE_OIDC_METADATA_URL = (
    "https://accounts.google.com/.well-known/openid-configuration"
)
TRUSTED_HOSTS = tuple(
    host.strip().lower()
    for host in _get_str(
        "TRUSTED_HOSTS",
        "casino.shingoon.me,www.casino.shingoon.me,"
        "dashboard.shingoon.me,dashboard-kaekun.pythonanywhere.com",
    ).split(",")
    if host.strip()
)
DASHBOARD_PUBLIC_URL = _get_str(
    "DASHBOARD_PUBLIC_URL", "https://casino.shingoon.me"
).rstrip("/")


# ============================================================
# 운영 시간 (KPI/실적 조회 기준일 = 한국시간 기준 오늘)
# ============================================================

TIMEZONE = "Asia/Seoul"


# ============================================================
# 로그
# ============================================================

LOG_DIR = _get_str("LOG_DIR", str(BASE_DIR / "logs"))
LOG_LEVEL = _get_str("LOG_LEVEL", "INFO")
LOG_MAX_BYTES = _get_int("LOG_MAX_BYTES", 5 * 1024 * 1024)
LOG_BACKUP_COUNT = _get_int("LOG_BACKUP_COUNT", 5)


class ConfigError(Exception):
    """환경변수 설정 오류. 메시지에 실제 값은 절대 포함하지 않는다."""


def validate_environment(require_ai=False, require_dart=False, require_law=False):
    """단계별 필수 환경변수를 확인한다. 값 자체는 예외 메시지에 노출하지 않는다."""
    missing = []

    if not FLASK_SECRET_KEY:
        missing.append("FLASK_SECRET_KEY")
    if not NEWS_DB_FILE:
        missing.append("NEWS_DB_FILE")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if require_ai and not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if require_dart and not DART_API_KEY:
        missing.append("DART_API_KEY")
    if require_law and not (LAW_API_OC and LAW_API_KEY):
        missing.append("LAW_API_OC / LAW_API_KEY")

    if missing:
        raise ConfigError("다음 환경변수가 없습니다: " + ", ".join(missing))


def known_secrets():
    """로그에 절대 노출되면 안 되는 값들의 목록(로그 마스킹용)."""
    return [
        value
        for value in (
            TELEGRAM_BOT_TOKEN,
            OPENAI_API_KEY,
            GEMINI_API_KEY,
            DART_API_KEY,
            LAW_API_KEY,
            FLASK_SECRET_KEY,
            GOOGLE_CLIENT_SECRET,
        )
        if value
    ]
