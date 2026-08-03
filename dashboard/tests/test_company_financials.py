import json

from dashboard_db import schema
from scripts.import_company_financials import import_financials
from services import company_intelligence


def _payload():
    return {
        "schema_version": 1,
        "provider": "VALUESearch",
        "reports": [
            {
                "company_name": "테스트카지노",
                "legal_name": "(주)테스트카지노",
                "provider_company_code": "N000001",
                "statement_type": "income_statement",
                "accounting_standard": "IFRS",
                "currency": "KRW",
                "unit": "KRW",
                "report_as_of": "2026-08-03",
                "source_filename": "income.xlsx",
                "source_sha256": "a" * 64,
                "values": [
                    {
                        "account_code": "121000",
                        "account_name": "수익",
                        "account_depth": 0,
                        "display_order": 0,
                        "fiscal_date": "2024-12-31",
                        "period_type": "annual",
                        "amount": 10_000_000_000,
                    },
                    {
                        "account_code": "121000",
                        "account_name": "수익",
                        "account_depth": 0,
                        "display_order": 0,
                        "fiscal_date": "2025-12-31",
                        "period_type": "annual",
                        "amount": 12_340_000_000,
                    },
                ],
            }
        ],
    }


def test_import_is_idempotent_and_preserves_existing_data(tmp_path):
    db_path = tmp_path / "dashboard.db"
    data_path = tmp_path / "financials.json"
    data_path.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")
    connection = schema.connect(str(db_path))
    connection.execute(
        "INSERT INTO monitored_companies (name, aliases_json, active, created_at) VALUES (?, ?, 1, ?)",
        ("기존회사", "[]", "2026-08-03T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()

    first = import_financials(db_path, data_path)
    second = import_financials(db_path, data_path)

    connection = schema.connect(str(db_path))
    assert first == second == {"companies": 1, "reports": 1, "values": 2, "integrity": "ok"}
    assert connection.execute("SELECT COUNT(*) FROM company_financial_reports").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM company_financial_values").fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM monitored_companies WHERE name = '기존회사'"
    ).fetchone()[0] == 1
    connection.close()


def test_financial_statement_context_uses_recent_periods_and_억원(db_connection):
    report = _payload()["reports"][0]
    db_connection.execute(
        """
        INSERT INTO company_financial_reports (
            company_name, legal_name, provider, provider_company_code,
            statement_type, accounting_standard, currency, unit, report_as_of,
            source_filename, source_sha256, imported_at
        ) VALUES (?, ?, 'VALUESearch', ?, ?, 'IFRS', 'KRW', 'KRW', ?, ?, ?, ?)
        """,
        (
            report["company_name"], report["legal_name"], report["provider_company_code"],
            report["statement_type"], report["report_as_of"], report["source_filename"],
            report["source_sha256"], "2026-08-03T00:00:00+00:00",
        ),
    )
    report_id = db_connection.execute("SELECT id FROM company_financial_reports").fetchone()[0]
    db_connection.executemany(
        """
        INSERT INTO company_financial_values (
            report_id, account_code, account_name, account_depth, display_order,
            fiscal_date, period_type, amount
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                report_id, value["account_code"], value["account_name"],
                value["account_depth"], value["display_order"], value["fiscal_date"],
                value["period_type"], value["amount"],
            )
            for value in report["values"]
        ],
    )
    db_connection.commit()

    statements = company_intelligence._build_company_financial_statements(
        db_connection, "테스트카지노"
    )

    assert statements[0]["title"] == "손익계산서"
    assert statements[0]["periods"] == ["2024-12-31", "2025-12-31"]
    assert statements[0]["rows"][0]["amounts"]["2025-12-31"]["display"] == "123.4"


def test_private_resorts_have_company_detail_profiles(db_connection):
    assert company_intelligence.get_company_profile_by_slug(db_connection, "인스파이어")
    assert company_intelligence.get_company_profile_by_slug(db_connection, "파라다이스세가사미")
