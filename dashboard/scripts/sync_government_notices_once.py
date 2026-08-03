"""Run only the government legislative-notice portion of law synchronization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard_db import queries  # noqa: E402
from extensions import dashboard_db  # noqa: E402
from scheduler.sync_law_updates import _sync_government_notices  # noqa: E402


def run():
    connection = dashboard_db()
    run_id = queries.start_analysis_run(connection, "government_notice_sync")
    try:
        new_count, error_count = _sync_government_notices(connection)
        status = "success" if error_count == 0 else "partial_failure"
        queries.finish_analysis_run(connection, run_id, status)
        total = connection.execute(
            "SELECT COUNT(*) FROM government_legislative_notices"
        ).fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "new": new_count,
            "errors": error_count,
            "total": total,
            "integrity": integrity,
        }
    except Exception as error:
        queries.finish_analysis_run(connection, run_id, "failed", str(error))
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    print(run())
