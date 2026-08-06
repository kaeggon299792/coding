"""Small, cached site-wide presentation settings."""

import os
import time

import config
from utils import now_kst


FONT_CHOICES = {
    "pretendard": "프리텐다드",
    "gowun-batang": "고운바탕",
    "hahmlet": "함렛",
}
DEFAULT_FONT = "pretendard"
_font_cache = {"value": DEFAULT_FONT, "expires": 0.0}

NUMBER_FONT_CHOICES = {
    "pretendard": "프리텐다드 숫자",
    "montserrat": "Montserrat 숫자",
    "trap": "Trap 숫자",
    "gowun-batang": "고운바탕 숫자",
    "hahmlet": "함렛 숫자",
}
DEFAULT_NUMBER_FONT = "pretendard"
_number_font_cache = {"value": DEFAULT_NUMBER_FONT, "expires": 0.0}

DEFAULT_ANIMATIONS_ENABLED = True
_animations_cache = {
    "value": DEFAULT_ANIMATIONS_ENABLED,
    "expires": 0.0,
    "database": None,
}


def _database_identity():
    return os.path.abspath(os.fspath(config.DASHBOARD_DB_FILE))


def get_cached_fonts():
    """Return both presentation settings without opening the DB when warm."""
    now = time.monotonic()
    if _font_cache["expires"] > now and _number_font_cache["expires"] > now:
        return _font_cache["value"], _number_font_cache["value"]
    return None


def get_cached_default_animations_enabled():
    if (
        _animations_cache["database"] == _database_identity()
        and _animations_cache["expires"] > time.monotonic()
    ):
        return _animations_cache["value"]
    return None


def get_default_animations_enabled(connection):
    now = time.monotonic()
    database = _database_identity()
    if (
        _animations_cache["database"] == database
        and _animations_cache["expires"] > now
    ):
        return _animations_cache["value"]
    row = connection.execute(
        "SELECT setting_value FROM site_settings "
        "WHERE setting_key='default_animations_enabled'"
    ).fetchone()
    value = (
        str(row["setting_value"]).strip().lower() in {"1", "true", "yes", "on"}
        if row else DEFAULT_ANIMATIONS_ENABLED
    )
    _animations_cache.update(value=value, expires=now + 60.0, database=database)
    return value


def set_default_animations_enabled(connection, enabled, user_id):
    value = bool(enabled)
    timestamp = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """INSERT INTO site_settings(setting_key, setting_value, updated_by, updated_at)
           VALUES ('default_animations_enabled', ?, ?, ?)
           ON CONFLICT(setting_key) DO UPDATE SET
             setting_value=excluded.setting_value,
             updated_by=excluded.updated_by,
             updated_at=excluded.updated_at""",
        ("1" if value else "0", user_id, timestamp),
    )
    connection.commit()
    _animations_cache.update(
        value=value,
        expires=time.monotonic() + 60.0,
        database=_database_identity(),
    )


def get_site_font(connection):
    now = time.monotonic()
    if _font_cache["expires"] > now:
        return _font_cache["value"]
    row = connection.execute(
        "SELECT setting_value FROM site_settings WHERE setting_key='site_font'"
    ).fetchone()
    value = row["setting_value"] if row and row["setting_value"] in FONT_CHOICES else DEFAULT_FONT
    _font_cache.update(value=value, expires=now + 60.0)
    return value


def set_site_font(connection, value, user_id):
    if value not in FONT_CHOICES:
        raise ValueError("지원하지 않는 글꼴입니다.")
    timestamp = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """INSERT INTO site_settings(setting_key, setting_value, updated_by, updated_at)
           VALUES ('site_font', ?, ?, ?)
           ON CONFLICT(setting_key) DO UPDATE SET
             setting_value=excluded.setting_value,
             updated_by=excluded.updated_by,
             updated_at=excluded.updated_at""",
        (value, user_id, timestamp),
    )
    connection.commit()
    _font_cache.update(value=value, expires=time.monotonic() + 60.0)


def get_number_font(connection):
    now = time.monotonic()
    if _number_font_cache["expires"] > now:
        return _number_font_cache["value"]
    row = connection.execute(
        "SELECT setting_value FROM site_settings WHERE setting_key='number_font'"
    ).fetchone()
    value = (
        row["setting_value"]
        if row and row["setting_value"] in NUMBER_FONT_CHOICES
        else DEFAULT_NUMBER_FONT
    )
    _number_font_cache.update(value=value, expires=now + 60.0)
    return value


def set_number_font(connection, value, user_id):
    if value not in NUMBER_FONT_CHOICES:
        raise ValueError("지원하지 않는 숫자 글꼴입니다.")
    timestamp = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """INSERT INTO site_settings(setting_key, setting_value, updated_by, updated_at)
           VALUES ('number_font', ?, ?, ?)
           ON CONFLICT(setting_key) DO UPDATE SET
             setting_value=excluded.setting_value,
             updated_by=excluded.updated_by,
             updated_at=excluded.updated_at""",
        (value, user_id, timestamp),
    )
    connection.commit()
    _number_font_cache.update(value=value, expires=time.monotonic() + 60.0)
