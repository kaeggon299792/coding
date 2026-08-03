"""
DB 커넥션 헬퍼.

- dashboard_db(): 대시보드 자체 DB, 읽기/쓰기 가능(migrate 포함).
- news_db_readonly(): 기존 뉴스 프로그램의 DB에
  URI 모드로 read-only 연결한다. 이 연결로는 물리적으로 INSERT/UPDATE/DELETE가
  불가능하므로(SQLite가 자체적으로 거부), 실수로라도 기존 데이터를 손상시킬 수 없다.
"""

import os
import sqlite3
import threading

import config
from dashboard_db import schema as dashboard_schema


_migration_lock = threading.Lock()
_migrated_database_identities = set()


def _database_identity(path):
    """Return an identity that changes if a DB file is replaced at the same path."""
    normalized = os.path.abspath(os.fspath(path))
    try:
        stat = os.stat(normalized)
    except OSError:
        return (normalized, None, None)
    return (normalized, stat.st_dev, stat.st_ino)


def dashboard_db():
    path = config.DASHBOARD_DB_FILE
    # Separate in-memory connections do not share a schema, so each one must
    # still be initialized independently.
    if os.fspath(path) == ":memory:":
        return dashboard_schema.connect(path)

    connection = dashboard_schema.connect(path, run_migrations=False)
    identity = _database_identity(path)
    if identity not in _migrated_database_identities:
        with _migration_lock:
            if identity not in _migrated_database_identities:
                try:
                    if not dashboard_schema.is_current(connection):
                        dashboard_schema.migrate(connection)
                except Exception:
                    connection.close()
                    raise
                _migrated_database_identities.add(identity)
    return connection


def _readonly_connect(path):
    if not path:
        return None
    uri = f"file:{path}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.OperationalError:
        # DB 파일이 아직 없거나 경로가 잘못된 경우 - 대시보드 전체를 중단시키지 않는다.
        return None


def news_db_readonly():
    return _readonly_connect(config.NEWS_DB_FILE)
