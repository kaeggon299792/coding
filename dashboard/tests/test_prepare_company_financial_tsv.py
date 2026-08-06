import json
from pathlib import Path

from dashboard_db import schema
from scripts.import_company_financials import import_financials
from scripts.prepare_company_financial_tsv import parse_report


def test_parse_report_preserves_cumulative_period_types(tmp_path):
    source = tmp_path / "statement.tsv"
    source.write_text(
        "코드\t계정명\t2025-03-31/1st Quarter\t2025-06-30/Semi Annual\t"
        "2025-09-30/3rd Quarter\t2025-12-31/Annual\n"
        "121000\t수익\t100\t220\t360\t500\n"
        "124001\t   [총종업원급여]\t20\t45\t70\t100\n",
        encoding="utf-8",
    )
    report = parse_report(source, "테스트", "(주)테스트")
    assert report["report_as_of"] == "2025-12-31"
    assert report["source_sha256"]
    revenue = [row for row in report["values"] if row["account_code"] == "121000"]
    assert [row["period_type"] for row in revenue] == [
        "quarter_1", "semiannual", "nine_month", "annual"
    ]
    personnel = next(row for row in report["values"] if row["account_code"] == "124001")
    assert personnel["account_depth"] == 1


def test_supplied_consolidated_statements_import_to_central_database(tmp_path):
    data_path = (
        Path(__file__).parents[1]
        / "data" / "company_financials_consolidated_20260806.json"
    )
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert {report["company_name"] for report in payload["reports"]} == {
        "GKL", "롯데관광개발", "파라다이스", "인스파이어"
    }
    db_path = tmp_path / "company-financials.db"
    result = import_financials(db_path, data_path)
    assert result == {"companies": 4, "reports": 4, "values": 3197, "integrity": "ok"}
    connection = schema.connect(db_path)
    gkl_periods = connection.execute(
        """
        SELECT DISTINCT value.period_type
        FROM company_financial_values AS value
        JOIN company_financial_reports AS report ON report.id=value.report_id
        WHERE report.company_name='GKL' AND value.account_code='121000'
        """
    ).fetchall()
    assert {row["period_type"] for row in gkl_periods} == {
        "quarter_1", "semiannual", "nine_month", "annual"
    }
    inspire_personnel = connection.execute(
        """
        SELECT COUNT(*)
        FROM company_financial_values AS value
        JOIN company_financial_reports AS report ON report.id=value.report_id
        WHERE report.company_name='인스파이어' AND value.account_code='124001'
        """
    ).fetchone()[0]
    assert inspire_personnel == 0
    connection.close()
