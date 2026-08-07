from types import SimpleNamespace

import pytest

from services import pythonanywhere_status


@pytest.fixture(autouse=True)
def reset_status_cache():
    pythonanywhere_status._reset_cache_for_tests()
    yield
    pythonanywhere_status._reset_cache_for_tests()


def test_cpu_status_uses_official_api_and_calculates_remaining(monkeypatch):
    monkeypatch.setattr("config.PYTHONANYWHERE_USERNAME", "account-name")
    monkeypatch.setattr("config.PYTHONANYWHERE_API_TOKEN", "private-token")
    monkeypatch.setattr("config.PYTHONANYWHERE_API_TIMEOUT_SECONDS", 6)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "daily_cpu_limit_seconds": 100_000,
                "daily_cpu_total_usage_seconds": 42_000,
                "next_reset_time": "2026-08-08T00:00:00Z",
            }

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(pythonanywhere_status.requests, "get", fake_get)
    result = pythonanywhere_status._cpu_status()

    assert result["usage_percent"] == 42.0
    assert result["remaining_seconds"] == 58_000
    assert captured["url"].endswith("/user/account-name/cpu/")
    assert captured["headers"] == {"Authorization": "Token private-token"}
    assert captured["timeout"] == 6


def test_storage_status_uses_home_without_shell_and_calculates_quota(monkeypatch):
    monkeypatch.setattr("config.PYTHONANYWHERE_DISK_QUOTA_GB", 5.0)
    monkeypatch.setattr("config.PYTHONANYWHERE_DISK_TIMEOUT_SECONDS", 20)
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(stdout=f"{2 * 1024 ** 3}\t/home/account\n")

    monkeypatch.setattr(pythonanywhere_status.subprocess, "run", fake_run)
    result = pythonanywhere_status._storage_status()

    assert captured["command"] == [
        "du", "-s", "-B", "1", "--one-file-system",
        str(pythonanywhere_status.Path.home().resolve()),
    ]
    assert "shell" not in captured
    assert captured["timeout"] == 20
    assert result["usage_percent"] == 40.0
    assert result["remaining_bytes"] == 3 * 1024 ** 3


def test_status_cache_reuses_snapshot_and_preserves_each_last_good_value(monkeypatch):
    monkeypatch.setattr("config.PYTHONANYWHERE_STATUS_CACHE_SECONDS", 300)
    snapshots = [
        {
            "cpu": {"available": True, "usage_percent": 12.0},
            "storage": {"available": True, "usage_percent": 34.0},
            "checked_at": "first", "stale": False,
        },
        {
            "cpu": {"available": False},
            "storage": {"available": True, "usage_percent": 35.0},
            "checked_at": "second", "stale": False,
        },
    ]
    calls = []

    def collect():
        calls.append(True)
        return snapshots.pop(0)

    monkeypatch.setattr(pythonanywhere_status, "_collect", collect)
    first = pythonanywhere_status.get_status()
    cached = pythonanywhere_status.get_status()
    refreshed = pythonanywhere_status.get_status(force=True)

    assert first == cached
    assert len(calls) == 2
    assert refreshed["cpu"]["usage_percent"] == 12.0
    assert refreshed["storage"]["usage_percent"] == 35.0
    assert refreshed["stale"] is True


def test_missing_configuration_is_safe(monkeypatch):
    monkeypatch.setattr("config.PYTHONANYWHERE_USERNAME", "")
    monkeypatch.setattr("config.PYTHONANYWHERE_API_TOKEN", "")
    monkeypatch.setattr("config.PYTHONANYWHERE_DISK_QUOTA_GB", None)

    result = pythonanywhere_status.get_status(force=True)

    assert result["cpu"] == {"available": False}
    assert result["storage"] == {"available": False}
    assert "token" not in str(result).lower()
