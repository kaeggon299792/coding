import sqlite3

from services import site_preferences


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE site_settings (
            setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL,
            updated_by INTEGER, updated_at TEXT NOT NULL
        )"""
    )
    return connection


def test_site_font_defaults_and_updates():
    connection = _connection()
    site_preferences._font_cache["expires"] = 0
    assert site_preferences.get_site_font(connection) == "pretendard"
    site_preferences.set_site_font(connection, "gowun-batang", 1)
    assert site_preferences.get_site_font(connection) == "gowun-batang"


def test_site_font_rejects_unknown_value():
    connection = _connection()
    try:
        site_preferences.set_site_font(connection, "external-script", 1)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown fonts must be rejected")


def test_number_font_defaults_and_updates():
    connection = _connection()
    site_preferences._number_font_cache["expires"] = 0
    assert site_preferences.get_number_font(connection) == "pretendard"
    site_preferences.set_number_font(connection, "trap", 1)
    assert site_preferences.get_number_font(connection) == "trap"
    site_preferences.set_number_font(connection, "montserrat", 1)
    assert site_preferences.get_number_font(connection) == "montserrat"


def test_number_font_rejects_unknown_value():
    connection = _connection()
    try:
        site_preferences.set_number_font(connection, "remote-font", 1)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown number fonts must be rejected")
