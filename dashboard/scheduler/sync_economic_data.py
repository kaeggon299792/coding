"""유가·환율 데이터를 수집한다."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard_db import queries
from extensions import dashboard_db
from services import economic_data
from utils import setup_logger
logger = setup_logger("economic_data_sync")

def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "economic_data_sync")
    try:
        results = (economic_data.fetch_oil(), economic_data.fetch_exchange())
        items = [item for result in results for item in result["items"]]
        errors = [error for result in results for error in result["errors"]]
        for item in items: queries.upsert_economic_observation(connection, item)
        queries.finish_analysis_run(connection, run_id, "success" if not errors else ("partial_failure" if items else "failed"), "; ".join(errors[:10]) if errors else None)
        logger.info("유가·환율 동기화 완료: 저장 %d건, 오류 %d건", len(items), len(errors))
    finally: connection.close()

if __name__ == "__main__": run()
