"""운영 DB의 기존 핵심 건수와 중앙 재무 데이터 무결성을 점검한다."""

import argparse
import json
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    connection = sqlite3.connect(str(args.database))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        result = {
            "users": connection.execute("SELECT COUNT(1) FROM dashboard_users").fetchone()[0],
            "research_documents": connection.execute(
                "SELECT COUNT(1) FROM research_documents"
            ).fetchone()[0],
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
        }
        if "company_financial_reports" in tables:
            result.update({
                "financial_companies": connection.execute(
                    "SELECT COUNT(DISTINCT company_name) FROM company_financial_reports"
                ).fetchone()[0],
                "financial_reports": connection.execute(
                    "SELECT COUNT(1) FROM company_financial_reports"
                ).fetchone()[0],
                "financial_values": connection.execute(
                    "SELECT COUNT(1) FROM company_financial_values"
                ).fetchone()[0],
            })
        if "company_credit_ratings" in tables:
            result.update({
                "credit_companies": connection.execute(
                    "SELECT COUNT(DISTINCT company_name) FROM company_credit_ratings"
                ).fetchone()[0],
                "credit_ratings": connection.execute(
                    "SELECT COUNT(1) FROM company_credit_ratings"
                ).fetchone()[0],
            })
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
