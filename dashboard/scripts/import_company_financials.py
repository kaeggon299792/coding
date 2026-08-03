"""정규화된 VALUESearch 재무제표를 중앙 SQLite DB에 멱등 반영한다."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_db import schema


ALLOWED_STATEMENT_TYPES = {"balance_sheet", "income_statement", "cash_flow"}


def _validated_reports(payload):
    if payload.get("schema_version") != 1:
        raise ValueError("지원하지 않는 재무 데이터 스키마입니다.")
    reports = payload.get("reports")
    if not isinstance(reports, list) or not reports:
        raise ValueError("반영할 재무 보고서가 없습니다.")
    seen = set()
    for report in reports:
        required = (
            "company_name", "legal_name", "statement_type", "source_filename",
            "source_sha256", "values",
        )
        if any(not report.get(field) for field in required):
            raise ValueError(f"필수 보고서 값이 없습니다: {report.get('source_filename')}")
        if report["statement_type"] not in ALLOWED_STATEMENT_TYPES:
            raise ValueError(f"알 수 없는 재무제표 종류: {report['statement_type']}")
        key = (report["company_name"], report["statement_type"])
        if key in seen:
            raise ValueError(f"회사·재무제표 중복: {key}")
        seen.add(key)
        for value in report["values"]:
            if not isinstance(value.get("amount"), int) or isinstance(value.get("amount"), bool):
                raise ValueError(f"원 단위 정수 금액이 아닙니다: {key}")
    return reports


def import_financials(database_path, data_path):
    payload = json.loads(Path(data_path).read_text(encoding="utf-8"))
    reports = _validated_reports(payload)
    connection = schema.connect(str(database_path))
    imported_at = datetime.now(timezone.utc).isoformat()
    inserted_values = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for report in reports:
            connection.execute(
                """
                INSERT INTO company_financial_reports (
                    company_name, legal_name, provider, provider_company_code,
                    statement_type, accounting_standard, currency, unit,
                    report_as_of, source_filename, source_sha256, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_name, statement_type, source_sha256) DO UPDATE SET
                    legal_name = excluded.legal_name,
                    provider = excluded.provider,
                    provider_company_code = excluded.provider_company_code,
                    accounting_standard = excluded.accounting_standard,
                    currency = excluded.currency,
                    unit = excluded.unit,
                    report_as_of = excluded.report_as_of,
                    source_filename = excluded.source_filename,
                    imported_at = excluded.imported_at
                """,
                (
                    report["company_name"], report["legal_name"], payload.get("provider") or "VALUESearch",
                    report.get("provider_company_code"), report["statement_type"],
                    report.get("accounting_standard"), report.get("currency") or "KRW",
                    report.get("unit") or "KRW", report.get("report_as_of"),
                    report["source_filename"], report["source_sha256"], imported_at,
                ),
            )
            report_id = connection.execute(
                """
                SELECT id FROM company_financial_reports
                WHERE company_name = ? AND statement_type = ? AND source_sha256 = ?
                """,
                (report["company_name"], report["statement_type"], report["source_sha256"]),
            ).fetchone()["id"]
            connection.execute(
                "DELETE FROM company_financial_values WHERE report_id = ?",
                (report_id,),
            )
            connection.executemany(
                """
                INSERT INTO company_financial_values (
                    report_id, account_code, account_name, account_depth,
                    display_order, fiscal_date, period_type, amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        report_id, value["account_code"], value["account_name"],
                        value.get("account_depth", 0), value["display_order"],
                        value["fiscal_date"], value["period_type"], value["amount"],
                    )
                    for value in report["values"]
                ],
            )
            inserted_values += len(report["values"])
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check 실패: {integrity}")
        return {
            "companies": len({report["company_name"] for report in reports}),
            "reports": len(reports),
            "values": inserted_values,
            "integrity": integrity,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_file", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    result = import_financials(args.database, args.data_file)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
