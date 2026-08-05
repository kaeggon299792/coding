"""Persistent, validated settings for jobs managed by CASINOINBOT."""

from __future__ import annotations

import json

from utils import now_kst


SETTING_KEY = "casinoinbot_task_settings_v1"

DEFAULTS = {
    "email_monitor": {"enabled": True, "timing": "continuous", "interval_minutes": 5, "notify_error": True, "notify_success": False},
    "casino_news_watch": {"enabled": True, "timing": "continuous", "interval_minutes": 15, "notify_error": True, "notify_success": False},
    "telegram_ingest": {"enabled": True, "timing": "continuous", "interval_minutes": 1, "notify_error": True, "notify_success": False},
    "law_sync": {"enabled": True, "timing": "daily", "hour_utc": 12, "minute_utc": 0, "notify_error": True, "notify_success": False},
    "daily_insight": {"enabled": True, "timing": "daily", "hour_utc": 12, "minute_utc": 5, "notify_error": True, "notify_success": False},
    "dart_sync": {"enabled": True, "timing": "hourly", "minute_utc": 30, "notify_error": True, "notify_success": False},
    "tourism_stats_sync": {"enabled": True, "timing": "daily", "hour_utc": 6, "minute_utc": 27, "notify_error": True, "notify_success": False},
    "salary_sync": {"enabled": True, "timing": "daily", "hour_utc": 21, "minute_utc": 10, "notify_error": True, "notify_success": False},
    "recruitment_sync": {"enabled": True, "timing": "daily", "hour_utc": 21, "minute_utc": 20, "notify_error": True, "notify_success": False},
    "localization_translation": {"enabled": True, "timing": "daily", "hour_utc": 14, "minute_utc": 30, "notify_error": True, "notify_success": False},
}


def _validated(task_key, raw):
    if task_key not in DEFAULTS:
        raise ValueError("알 수 없는 자동화 작업입니다.")
    default = DEFAULTS[task_key]
    value = dict(default)
    if isinstance(raw, dict):
        value["enabled"] = bool(raw.get("enabled", default["enabled"]))
        value["notify_error"] = bool(raw.get("notify_error", default["notify_error"]))
        value["notify_success"] = bool(raw.get("notify_success", default["notify_success"]))
        if default["timing"] == "continuous":
            value["interval_minutes"] = max(1, min(1440, int(raw.get("interval_minutes", default["interval_minutes"]))))
        elif default["timing"] == "hourly":
            value["minute_utc"] = max(0, min(59, int(raw.get("minute_utc", default["minute_utc"]))))
        else:
            value["hour_utc"] = max(0, min(23, int(raw.get("hour_utc", default["hour_utc"]))))
            value["minute_utc"] = max(0, min(59, int(raw.get("minute_utc", default["minute_utc"]))))
    return value


def get_all(connection):
    row = connection.execute(
        "SELECT setting_value FROM site_settings WHERE setting_key=?", (SETTING_KEY,)
    ).fetchone()
    try:
        saved = json.loads(row["setting_value"]) if row else {}
    except (TypeError, ValueError):
        saved = {}
    return {key: _validated(key, saved.get(key, {})) for key in DEFAULTS}


def get_task(connection, task_key):
    return get_all(connection)[task_key]


def update_task(connection, task_key, values, user_id=None):
    settings = get_all(connection)
    settings[task_key] = _validated(task_key, values)
    timestamp = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """INSERT INTO site_settings(setting_key,setting_value,updated_by,updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(setting_key) DO UPDATE SET
             setting_value=excluded.setting_value,
             updated_by=excluded.updated_by,
             updated_at=excluded.updated_at""",
        (SETTING_KEY, json.dumps(settings, ensure_ascii=False, sort_keys=True), user_id, timestamp),
    )
    return settings[task_key]


def notifications_enabled(connection, task_key, *, success=False):
    if task_key not in DEFAULTS:
        return not success
    setting = get_task(connection, task_key)
    return bool(setting["notify_success" if success else "notify_error"])
