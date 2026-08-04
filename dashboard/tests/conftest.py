import os
import sys
from pathlib import Path

DASHBOARD_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DASHBOARD_ROOT))

import pytest  # noqa: E402

# 앱 모듈이 import 시점에 config를 읽으므로, 다른 모듈을 import하기 전에
# 테스트용 환경변수를 먼저 세팅한다.
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DASHBOARD_DB_FILE", ":memory:")
os.environ.setdefault("NEWS_DB_FILE", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "-1")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault("DASHBOARD_PUBLIC_URL", "https://www.casinoin.kr")
os.environ.setdefault(
    "TRUSTED_HOSTS",
    "www.casinoin.kr,casinoin.kr,casino.shingoon.me,"
    "www.casino.shingoon.me,dashboard.shingoon.me,"
    "dashboard-kaekun.pythonanywhere.com",
)
os.environ.setdefault(
    "GOOGLE_REDIRECT_URI", "https://www.casinoin.kr/auth/google/callback"
)


@pytest.fixture
def db_connection(tmp_path):
    """테스트마다 독립된 임시 SQLite 파일에 연결하고 마이그레이션을 실행한다."""
    from dashboard_db import schema

    db_path = tmp_path / "test_dashboard.db"
    connection = schema.connect(str(db_path))
    yield connection
    connection.close()
