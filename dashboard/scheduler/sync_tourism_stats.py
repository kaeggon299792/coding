"""방한 외래관광객 통계를 DB 캐시에 갱신하는 예약 작업."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard_db import queries
from extensions import dashboard_db
from services import tourism_stats_client
from utils import setup_logger

logger = setup_logger("tourism_stats_sync")
REFRESH_RECENT_MONTHS = 2


def target_year_months(latest_ym):
    year, latest_month = int(latest_ym[:4]), int(latest_ym[4:6])
    this_year = [f"{year}{month:02d}" for month in range(1, latest_month + 1)]
    last_year = [f"{year - 1}{month:02d}" for month in range(1, 13)]
    return this_year, last_year


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "tourism_stats_sync")
    try:
        latest_ym = tourism_stats_client.find_latest_available_ym()
        if not latest_ym:
            raise RuntimeError("최근 발표된 관광 통계 월을 찾지 못했습니다.")
        this_year, last_year = target_year_months(latest_ym)
        cached = set(queries.list_tourism_yms(connection))
        refresh = set(this_year[-REFRESH_RECENT_MONTHS:])
        targets = [ym for ym in this_year + last_year if ym not in cached or ym in refresh]
        failures = []
        for ym in targets:
            result = tourism_stats_client.get_bucket_totals(ym)
            if not result.get("ok"):
                failures.append(f"{ym}: {result.get('error')}")
                continue
            for label, count in result["buckets"].items():
                queries.upsert_tourism_stat(connection, ym, label, count)
        status = "success" if not failures else "partial_failure"
        queries.finish_analysis_run(connection, run_id, status, "; ".join(failures))
        logger.info("관광 통계 동기화: 대상 %d개월, 실패 %d개월", len(targets), len(failures))
    except Exception as error:
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
        logger.error("관광 통계 동기화 실패: %s", error)
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    run()
