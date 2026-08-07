import importlib.util
import shutil
import sqlite3
import sys
from pathlib import Path

source = Path("dashboard.db")
sys.path.insert(0, ".")
target = Path("deployment/community-test.db")
shutil.copy2(source, target)
spec = importlib.util.spec_from_file_location("community_schema", "deployment/community-schema.py")
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)
connection = schema.connect(target)
columns = {row[1] for row in connection.execute("PRAGMA table_info(community_comments)")}
assert {"post_id", "author_id", "content", "is_deleted", "deleted_by"} <= columns
tables = {
    row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
}
assert {
    "comment_notification_subscriptions",
    "comment_notification_rate_limits",
    "comment_notification_deliveries",
} <= tables
assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
connection.close()
target.unlink()
print("COMMUNITY_SCHEMA_OK")
