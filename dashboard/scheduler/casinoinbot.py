"""Single PythonAnywhere Always-on supervisor for CASINO IN background work.

The process keeps the three existing long-running workers alive and starts the
seven former Scheduled Tasks at their existing UTC times.  Child commands keep
their original interpreters and working directories, so this consolidation
does not merge virtualenvs or application state.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from extensions import dashboard_db
from services import automation_settings, telegram_alert

try:
    import fcntl
except ImportError:  # pragma: no cover - production runs on Linux
    fcntl = None


MGMT_PYTHON = "/home/kaekun/.virtualenvs/mgmt-dashboard/bin/python"
STATE_DIR = Path(os.environ.get("CASINOINBOT_STATE_DIR", "/home/kaekun/.local/state"))
STATE_FILE = STATE_DIR / "casinoinbot.json"
LOCK_FILE = STATE_DIR / "casinoinbot.lock"
CHECK_INTERVAL_SECONDS = 10
RESTART_DELAY_SECONDS = 30


@dataclass(frozen=True)
class Worker:
    name: str
    command: tuple[str, ...]
    cwd: str


@dataclass(frozen=True)
class Schedule:
    name: str
    command: tuple[str, ...]
    cwd: str
    hour: int | None = None
    minute: int = 0
    hourly: bool = False


WORKERS = (
    Worker(
        "email_monitor",
        ("python3", str(PROJECT_ROOT / "scheduler/email_monitor_managed.py")),
        "/home/kaekun/email_monitor",
    ),
    Worker(
        "casino_news_watch",
        (
            "/home/kaekun/.virtualenvs/casino_news_watch/bin/python",
            str(PROJECT_ROOT / "scheduler/casino_news_watch_managed.py"),
        ),
        "/home/kaekun/casino_news_watch",
    ),
    Worker(
        "telegram_ingest",
        (MGMT_PYTHON, str(PROJECT_ROOT / "scheduler/poll_telegram_performance.py")),
        str(PROJECT_ROOT),
    ),
)


def _scheduled(name: str, script: str, hour: int | None, minute: int, *, hourly=False):
    return Schedule(
        name,
        (MGMT_PYTHON, str(PROJECT_ROOT / f"scheduler/{script}")),
        str(PROJECT_ROOT),
        hour=hour,
        minute=minute,
        hourly=hourly,
    )


SCHEDULES = (
    _scheduled("law_sync", "sync_law_updates.py", 12, 0),
    _scheduled("daily_insight", "daily_insight_batch.py", 12, 5),
    _scheduled("dart_sync", "sync_dart_disclosures.py", None, 30, hourly=True),
    _scheduled("tourism_stats_sync", "sync_tourism_stats.py", 6, 27),
    _scheduled("salary_sync", "sync_salary_data.py", 21, 10),
    _scheduled("recruitment_sync", "sync_recruitment_jobs.py", 21, 20),
    _scheduled("localization_translation", "translate_localization.py", 14, 30),
)


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{stamp}] [CASINOINBOT] {message}", flush=True)


def due_slot(schedule: Schedule, now: datetime, setting=None) -> str | None:
    """Return the current due slot, including a missed slot later that day/hour."""
    current = now.astimezone(timezone.utc)
    setting = setting or {}
    minute = int(setting.get("minute_utc", schedule.minute))
    hourly = setting.get("timing") == "hourly" if setting else schedule.hourly
    hour = int(setting.get("hour_utc", schedule.hour or 0)) if not hourly else None
    if hourly:
        if current.minute < minute:
            return None
        return current.strftime("%Y-%m-%dT%H")
    if hour is None or (current.hour, current.minute) < (hour, minute):
        return None
    return current.strftime("%Y-%m-%d")


def load_state() -> dict[str, str]:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_state(state: dict[str, str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary.replace(STATE_FILE)


def seed_initial_state(now: datetime) -> dict[str, str]:
    """Mark already-due slots on first migration start to prevent duplicate runs."""
    state = {}
    for schedule in SCHEDULES:
        slot = due_slot(schedule, now)
        if slot:
            state[schedule.name] = slot
    save_state(state)
    return state


def validate_paths() -> list[str]:
    errors = []
    for item in (*WORKERS, *SCHEDULES):
        executable, *arguments = item.command
        if "/" in executable and not Path(executable).is_file():
            errors.append(f"missing executable: {executable}")
        for argument in arguments:
            if argument.endswith(".py") and not Path(argument).is_file():
                errors.append(f"missing script: {argument}")
        if not Path(item.cwd).is_dir():
            errors.append(f"missing working directory: {item.cwd}")
    return errors


class Supervisor:
    def __init__(self) -> None:
        self.stopping = False
        self.workers: dict[str, subprocess.Popen] = {}
        self.worker_started_at: dict[str, float] = {}
        self.scheduled: dict[str, tuple[str, subprocess.Popen]] = {}
        self.settings = self._load_settings()
        self.settings_loaded_at = time.monotonic()
        self.worker_config: dict[str, str] = {}
        self.last_error_alert: dict[str, float] = {}
        self.state = load_state()
        if not STATE_FILE.exists():
            self.state = seed_initial_state(datetime.now(timezone.utc))
            log("initial schedule state seeded; already-due legacy tasks will not run twice")

    @staticmethod
    def _load_settings():
        connection = dashboard_db()
        try:
            return automation_settings.get_all(connection)
        finally:
            connection.close()

    @staticmethod
    def _environment(name, setting):
        environment = os.environ.copy()
        environment["CASINOIN_TASK_KEY"] = name
        environment["CASINOIN_NOTIFY_ON_ERROR"] = "1" if setting.get("notify_error", True) else "0"
        environment["CASINOIN_NOTIFY_ON_SUCCESS"] = "1" if setting.get("notify_success", False) else "0"
        if setting.get("timing") == "continuous":
            seconds = str(max(60, int(setting.get("interval_minutes", 1)) * 60))
            if name == "email_monitor":
                environment["RUN_FOREVER_INTERVAL_SECONDS"] = seconds
            elif name == "casino_news_watch":
                environment["CASINO_NEWS_INTERVAL_SECONDS"] = seconds
            elif name == "telegram_ingest":
                environment["TELEGRAM_POLL_INTERVAL_SECONDS"] = seconds
        return environment

    def _start(self, item: Worker | Schedule, setting) -> subprocess.Popen:
        return subprocess.Popen(
            item.command, cwd=item.cwd, env=self._environment(item.name, setting)
        )

    def _notify_error(self, name, message):
        setting = self.settings.get(name, {})
        if not setting.get("notify_error", True):
            return
        now = time.monotonic()
        if now - self.last_error_alert.get(name, 0) < 3600:
            return
        self.last_error_alert[name] = now
        telegram_alert.send_alert(
            f"⚠️ <b>CASINOINBOT 작업 오류</b>\n\n작업: {name}\n오류: {message[:1000]}\n\n정상·무변화 알림은 발송하지 않습니다.",
            force=True,
        )

    def _notify_success(self, name, slot):
        if not self.settings.get(name, {}).get("notify_success", False):
            return
        telegram_alert.send_alert(
            f"✅ <b>CASINOINBOT 작업 완료</b>\n\n작업: {name}\n실행 구간: {slot}",
            force=True,
        )

    def start_worker(self, worker: Worker) -> None:
        setting = self.settings[worker.name]
        self.workers[worker.name] = self._start(worker, setting)
        self.worker_started_at[worker.name] = time.monotonic()
        self.worker_config[worker.name] = json.dumps(setting, sort_keys=True)
        log(f"worker started: {worker.name} pid={self.workers[worker.name].pid}")

    def maintain_workers(self) -> None:
        for worker in WORKERS:
            setting = self.settings[worker.name]
            if not setting.get("enabled", True):
                process = self.workers.pop(worker.name, None)
                if process and process.poll() is None:
                    process.terminate()
                    log(f"worker disabled: {worker.name}")
                continue
            process = self.workers.get(worker.name)
            if process is None:
                self.start_worker(worker)
                continue
            code = process.poll()
            if code is None:
                signature = json.dumps(setting, sort_keys=True)
                if self.worker_config.get(worker.name) != signature:
                    process.terminate()
                    self.workers.pop(worker.name, None)
                    log(f"worker settings changed; restarting: {worker.name}")
                continue
            elapsed = time.monotonic() - self.worker_started_at.get(worker.name, 0)
            if elapsed < RESTART_DELAY_SECONDS:
                continue
            log(f"worker exited: {worker.name} code={code}; restarting")
            if code:
                self._notify_error(worker.name, f"상시 작업 프로세스 종료 코드 {code}")
            self.start_worker(worker)

    def maintain_schedules(self, now: datetime) -> None:
        for name, (slot, process) in list(self.scheduled.items()):
            code = process.poll()
            if code is None:
                continue
            log(f"scheduled task finished: {name} slot={slot} code={code}")
            if code:
                self._notify_error(name, f"예약 작업 종료 코드 {code} (실행 구간 {slot})")
            else:
                self._notify_success(name, slot)
            self.scheduled.pop(name, None)

        for schedule in SCHEDULES:
            setting = self.settings[schedule.name]
            if not setting.get("enabled", True):
                continue
            slot = due_slot(schedule, now, setting)
            if not slot or self.state.get(schedule.name) == slot:
                continue
            if schedule.name in self.scheduled:
                continue
            # Save before spawning so a supervisor restart cannot duplicate a run.
            self.state[schedule.name] = slot
            save_state(self.state)
            process = self._start(schedule, setting)
            self.scheduled[schedule.name] = (slot, process)
            log(f"scheduled task started: {schedule.name} slot={slot} pid={process.pid}")

    def stop(self, *_args) -> None:
        self.stopping = True

    def shutdown(self) -> None:
        processes = list(self.workers.values()) + [item[1] for item in self.scheduled.values()]
        for process in processes:
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 15
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
        log("all child processes stopped")

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        log("supervisor started")
        try:
            while not self.stopping:
                if time.monotonic() - self.settings_loaded_at >= 30:
                    self.settings = self._load_settings()
                    self.settings_loaded_at = time.monotonic()
                self.maintain_workers()
                self.maintain_schedules(datetime.now(timezone.utc))
                time.sleep(CHECK_INTERVAL_SECONDS)
        finally:
            self.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate configured paths and exit")
    args = parser.parse_args()
    errors = validate_paths()
    if errors:
        for error in errors:
            log(error)
        return 1
    if args.check:
        log(f"configuration valid: {len(WORKERS)} workers, {len(SCHEDULES)} schedules")
        return 0

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_stream = LOCK_FILE.open("w", encoding="utf-8")
    if fcntl is not None:
        try:
            fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another CASINOINBOT supervisor is already running")
            return 1
    lock_stream.write(str(os.getpid()))
    lock_stream.flush()
    Supervisor().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
