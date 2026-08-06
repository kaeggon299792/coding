"""
관리용 커맨드라인 도구.

사용법:
  python manage.py create-user <username>              대화형으로 비밀번호 입력받아 계정 생성/재설정
  python manage.py list-users                           등록된 사용자 목록
  python manage.py add-company <회사명> <DART고유번호>    DART 관심기업 등록/수정
  python manage.py list-companies                       등록된 관심기업 목록
  python manage.py add-law <법령명>                      모니터링 법령 등록(관리자가 이름만 넣으면
                                                          다음 sync_law_updates.py 실행 시 자동으로
                                                          법령ID/MST를 검색해 채움)
  python manage.py seed-default-laws                     스펙에 예시로 나온 기본 모니터링 법령 목록을 일괄 등록

셀프 회원가입 화면은 없다(내부 업무용 시스템 - 관리자가 직접 콘솔에서 계정을 만든다).
DART 고유번호(corp_code)는 https://opendart.fss.or.kr 에서 회사명으로 검색해 확인한다.
"""

import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

import config
from dashboard_db import queries
from extensions import dashboard_db
from utils import now_kst


def _valid_password(value):
    return len(value) >= 8


def create_user(username):
    password = getpass.getpass("비밀번호: ")
    password_confirm = getpass.getpass("비밀번호 확인: ")
    if password != password_confirm:
        print("비밀번호가 일치하지 않습니다.", file=sys.stderr)
        return 1
    if not _valid_password(password):
        print("비밀번호는 8자 이상이어야 합니다.", file=sys.stderr)
        return 1

    connection = dashboard_db()
    try:
        existing = queries.get_user_by_username(connection, username)
        password_hash = generate_password_hash(password)
        if existing:
            changed_at = now_kst().isoformat()
            connection.execute(
                """UPDATE dashboard_users
                   SET password_hash=?, password_changed_at=?, updated_at=?
                   WHERE username=?""",
                (password_hash, changed_at, changed_at, username),
            )
            connection.execute(
                """UPDATE dashboard_active_sessions
                   SET revoked_at=?, revoke_reason='cli_password_reset'
                   WHERE user_id=? AND revoked_at IS NULL""",
                (changed_at, existing["id"]),
            )
            connection.execute(
                """UPDATE remember_login_tokens SET revoked_at=?
                   WHERE user_id=? AND revoked_at IS NULL""",
                (changed_at, existing["id"]),
            )
            connection.commit()
            print(f"기존 계정 '{username}'의 비밀번호를 재설정했습니다.")
        else:
            queries.create_user(connection, username, password_hash)
            print(f"계정 '{username}'을(를) 생성했습니다.")
    finally:
        connection.close()
    return 0


def list_users():
    connection = dashboard_db()
    try:
        rows = connection.execute(
            "SELECT username, created_at, last_login_at FROM dashboard_users ORDER BY id"
        ).fetchall()
        if not rows:
            print("등록된 사용자가 없습니다.")
            return 0
        for row in rows:
            print(f"{row['username']}\t생성: {row['created_at']}\t마지막 로그인: {row['last_login_at'] or '-'}")
    finally:
        connection.close()
    return 0


def add_company(name, dart_corp_code):
    connection = dashboard_db()
    try:
        queries.upsert_monitored_company(connection, name, dart_corp_code)
        print(f"관심기업 '{name}'({dart_corp_code})을(를) 등록했습니다.")
    finally:
        connection.close()
    return 0


def list_companies():
    connection = dashboard_db()
    try:
        rows = queries.list_monitored_companies(connection, active_only=False)
        if not rows:
            print("등록된 관심기업이 없습니다.")
            return 0
        for row in rows:
            print(f"{row['name']}\t{row['dart_corp_code']}\t{'활성' if row['active'] else '비활성'}")
    finally:
        connection.close()
    return 0


def add_law(law_name):
    connection = dashboard_db()
    try:
        queries.upsert_monitored_law(connection, law_name)
        print(f"모니터링 법령 '{law_name}'을(를) 등록했습니다(다음 동기화 시 자동으로 ID를 채웁니다).")
    finally:
        connection.close()
    return 0


def seed_default_laws():
    connection = dashboard_db()
    try:
        for law_name in config.DEFAULT_MONITORED_LAWS:
            queries.upsert_monitored_law(connection, law_name)
        print(f"기본 모니터링 법령 {len(config.DEFAULT_MONITORED_LAWS)}건을 등록했습니다.")
    finally:
        connection.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="대시보드 관리 도구")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-user", help="사용자 생성 또는 비밀번호 재설정")
    create_parser.add_argument("username")

    subparsers.add_parser("list-users", help="사용자 목록")

    company_parser = subparsers.add_parser("add-company", help="DART 관심기업 등록/수정")
    company_parser.add_argument("name")
    company_parser.add_argument("dart_corp_code")

    subparsers.add_parser("list-companies", help="관심기업 목록")

    law_parser = subparsers.add_parser("add-law", help="모니터링 법령 등록")
    law_parser.add_argument("law_name")

    subparsers.add_parser("seed-default-laws", help="기본 모니터링 법령 목록 일괄 등록")

    args = parser.parse_args()

    if args.command == "create-user":
        sys.exit(create_user(args.username))
    elif args.command == "list-users":
        sys.exit(list_users())
    elif args.command == "add-company":
        sys.exit(add_company(args.name, args.dart_corp_code))
    elif args.command == "list-companies":
        sys.exit(list_companies())
    elif args.command == "add-law":
        sys.exit(add_law(args.law_name))
    elif args.command == "seed-default-laws":
        sys.exit(seed_default_laws())


if __name__ == "__main__":
    main()
