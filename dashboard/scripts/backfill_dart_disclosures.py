"""Non-destructively backfill historical DART filings for monitored companies."""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from services import dart_client  # noqa: E402
from utils import now_kst  # noqa: E402


def _date_windows(start_date, end_date, window_days=180):
    cursor = start_date
    while cursor <= end_date:
        window_end = min(cursor + timedelta(days=window_days - 1), end_date)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def run(days=1095):
    if not config.DART_API_KEY:
        raise RuntimeError("DART_API_KEY is not configured")

    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "dart_backfill_3y")
    inserted = 0
    existing = 0
    errors = []
    end_date = now_kst().date()
    start_date = end_date - timedelta(days=max(1, int(days)))
    try:
        companies = queries.list_monitored_companies(connection, active_only=True)
        for company in companies:
            corp_code = company.get("dart_corp_code")
            if not corp_code:
                continue
            for window_start, window_end in _date_windows(start_date, end_date):
                page_no = 1
                while True:
                    result = dart_client.search_disclosures(
                        corp_code=corp_code,
                        start_date=window_start.strftime("%Y%m%d"),
                        end_date=window_end.strftime("%Y%m%d"),
                        page_no=page_no,
                        page_count=100,
                    )
                    if not result.get("ok"):
                        errors.append(f"{company['name']}:{window_start}:{result.get('error', 'unknown')}")
                        break
                    items = result.get("list") or []
                    for item in items:
                        rcept_no = item.get("rcept_no")
                        if not rcept_no:
                            continue
                        if queries.disclosure_exists(connection, rcept_no):
                            existing += 1
                            continue
                        report_name = item.get("report_nm") or ""
                        queries.save_disclosure(
                            connection,
                            rcept_no=rcept_no,
                            corp_name=item.get("corp_name") or company["name"],
                            dart_corp_code=corp_code,
                            report_nm=report_name,
                            pblntf_ty=item.get("pblntf_ty"),
                            rcept_dt=item.get("rcept_dt"),
                            flr_nm=item.get("flr_nm"),
                            dart_link=dart_client.build_dart_link(rcept_no),
                            is_important=dart_client.is_important_disclosure(report_name),
                        )
                        inserted += 1
                    total_pages = int(result.get("total_page") or 1)
                    if page_no >= total_pages or len(items) < 100:
                        break
                    page_no += 1
        status = "success" if not errors else "partial_failure"
        queries.finish_analysis_run(
            connection, run_id, status,
            "; ".join(errors[:10]) if errors else None,
        )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "inserted": inserted,
            "existing": existing,
            "errors": len(errors),
            "integrity": integrity,
        }
    except Exception as error:
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1095)
    args = parser.parse_args()
    print(run(days=args.days))
