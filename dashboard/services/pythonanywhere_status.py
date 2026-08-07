"""Cached, server-side PythonAnywhere account status for administrators."""

from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

import config


_cache_lock = threading.Lock()
_cache = {"value": None, "expires": 0.0}


def _percent(used: float, limit: float) -> float:
    if limit <= 0:
        return 0.0
    return round(max(0.0, min(100.0, used / limit * 100.0)), 1)


def _cpu_status() -> dict:
    username = config.PYTHONANYWHERE_USERNAME
    token = config.PYTHONANYWHERE_API_TOKEN
    if not username or not token:
        return {"available": False}

    response = requests.get(
        "https://www.pythonanywhere.com/api/v0/user/"
        f"{quote(username, safe='')}/cpu/",
        headers={"Authorization": f"Token {token}"},
        timeout=max(1, config.PYTHONANYWHERE_API_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    payload = response.json()
    limit = max(0.0, float(payload["daily_cpu_limit_seconds"]))
    used = max(0.0, float(payload["daily_cpu_total_usage_seconds"]))
    remaining = max(0.0, limit - used)
    return {
        "available": True,
        "limit_seconds": round(limit),
        "used_seconds": round(used),
        "remaining_seconds": round(remaining),
        "usage_percent": _percent(used, limit),
        "next_reset_time": str(payload.get("next_reset_time") or ""),
    }


def _storage_status() -> dict:
    quota_gb = config.PYTHONANYWHERE_DISK_QUOTA_GB
    if quota_gb is None or quota_gb <= 0:
        return {"available": False}

    home = Path.home().resolve()
    completed = subprocess.run(
        ["du", "-s", "-B", "1", "--one-file-system", str(home)],
        check=True,
        capture_output=True,
        text=True,
        timeout=max(1, config.PYTHONANYWHERE_DISK_TIMEOUT_SECONDS),
    )
    used_bytes = max(0, int(completed.stdout.split()[0]))
    quota_bytes = round(float(quota_gb) * 1024 ** 3)
    remaining_bytes = max(0, quota_bytes - used_bytes)
    return {
        "available": True,
        "used_bytes": used_bytes,
        "quota_bytes": quota_bytes,
        "remaining_bytes": remaining_bytes,
        "usage_percent": _percent(used_bytes, quota_bytes),
    }


def _collect() -> dict:
    try:
        cpu = _cpu_status()
    except (OSError, ValueError, KeyError, TypeError, requests.RequestException):
        cpu = {"available": False}
    try:
        storage = _storage_status()
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        storage = {"available": False}
    return {
        "cpu": cpu,
        "storage": storage,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stale": False,
    }


def get_status(*, force: bool = False) -> dict:
    """Return a cached status snapshot without exposing credentials or errors."""
    now = time.monotonic()
    with _cache_lock:
        if not force and _cache["value"] is not None and _cache["expires"] > now:
            return dict(_cache["value"])

        previous = _cache["value"]
        current = _collect()
        stale = False
        if previous:
            for key in ("cpu", "storage"):
                if not current[key]["available"] and previous[key]["available"]:
                    current[key] = dict(previous[key])
                    stale = True
        current["stale"] = stale

        ttl = max(30, config.PYTHONANYWHERE_STATUS_CACHE_SECONDS)
        _cache.update(value=current, expires=now + ttl)
        return dict(current)


def _reset_cache_for_tests() -> None:
    with _cache_lock:
        _cache.update(value=None, expires=0.0)
