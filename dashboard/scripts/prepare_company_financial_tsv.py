"""Convert user-provided tab-separated consolidated statements to import JSON."""

import argparse
import csv
import hashlib
import json
from pathlib import Path


PERIOD_TYPES = {
    "1st Quarter": "quarter_1",
    "Semi Annual": "semiannual",
    "3rd Quarter": "nine_month",
    "Annual": "annual",
}

REPORTS = (
    ("GKL", "그랜드코리아레저(주)", "gkl_consolidated_income_20260806.tsv"),
    ("롯데관광개발", "롯데관광개발(주)", "lotte_tour_consolidated_income_20260806.tsv"),
    ("파라다이스", "(주)파라다이스", "paradise_consolidated_income_20260806.tsv"),
    (
        "인스파이어", "(주)인스파이어인티그레이티드리조트",
        "inspire_consolidated_income_20260806.tsv",
    ),
)


def _depth(account_name):
    leading = len(account_name) - len(account_name.lstrip())
    return max(0, leading // 3)


def parse_report(source_path, company_name, legal_name):
    raw_bytes = source_path.read_bytes()
    rows = list(csv.reader(raw_bytes.decode("utf-8-sig").splitlines(), delimiter="\t"))
    if not rows or rows[0][:2] != ["코드", "계정명"]:
        raise ValueError(f"재무제표 헤더가 올바르지 않습니다: {source_path.name}")
    periods = []
    for column, heading in enumerate(rows[0][2:], start=2):
        try:
            fiscal_date, source_period = heading.split("/", 1)
        except ValueError as error:
            raise ValueError(f"기간 헤더가 올바르지 않습니다: {heading}") from error
        if source_period not in PERIOD_TYPES:
            raise ValueError(f"지원하지 않는 기간 유형입니다: {source_period}")
        periods.append((column, fiscal_date, PERIOD_TYPES[source_period]))

    values = []
    for display_order, row in enumerate(rows[1:]):
        if len(row) < 2 or not row[0].strip():
            continue
        account_code = row[0].strip()
        account_name_raw = row[1]
        for column, fiscal_date, period_type in periods:
            raw_amount = row[column].strip() if column < len(row) else ""
            if not raw_amount:
                continue
            try:
                amount = int(raw_amount.replace(",", ""))
            except ValueError as error:
                raise ValueError(
                    f"금액이 정수가 아닙니다: {source_path.name} {account_code} {fiscal_date}"
                ) from error
            values.append({
                "account_code": account_code,
                "account_name": account_name_raw.strip(),
                "account_depth": _depth(account_name_raw),
                "display_order": display_order,
                "fiscal_date": fiscal_date,
                "period_type": period_type,
                "amount": amount,
            })
    if not values:
        raise ValueError(f"저장할 재무 값이 없습니다: {source_path.name}")
    return {
        "company_name": company_name,
        "legal_name": legal_name,
        "statement_type": "income_statement",
        "accounting_standard": "IFRS",
        "currency": "KRW",
        "unit": "KRW",
        "report_as_of": max(period[1] for period in periods),
        "source_filename": source_path.name,
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "values": values,
    }


def build_payload(source_dir):
    return {
        "schema_version": 1,
        "provider": "User-provided VALUESearch export",
        "reports": [
            parse_report(source_dir / filename, company_name, legal_name)
            for company_name, legal_name, filename in REPORTS
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_payload(args.source_dir)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "reports": len(payload["reports"]),
        "values": sum(len(report["values"]) for report in payload["reports"]),
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
