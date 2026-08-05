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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - production runs on Linux
    fcntl = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
        ("python3", "/home/kaekun/email_monitor/run_forever.py"),
        "/home/kaekun/email_monitor",
    ),
    Worker(
        "casino_news_watch",
        (
            "/home/kaekun/.virtualenvs/casino_news_watch/bin/python",
            "/home/kaekun/casino_news_watch/always_on_runner.py",
        ),
        "/home/kaekun/casino_news_watch",
    ),
    Worker(
        "telegram_performance",
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
    _scheduled("tourism_stats", "sync_tourism_stats.py", 6, 27),
    _scheduled("salary_sync", "sync_salary_data.py", 21, 10),
    _scheduled("recruitment_sync", "sync_recruitment_jobs.py", 21, 20),
    _scheduled("localization_translation", "translate_localization.py", 14, 30),
)


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{stamp}] [CASINOINBOT] {message}", flush=True)


def due_slot(schedule: Schedule, now: datetime) -> str | None:
    """Return the current due slot, including a missed slot later that day/hour."""
    current = now.astimezone(timezone.utc)
    if schedule.hourly:
        if current.minute < schedule.minute:
            return None
        return current.strftime("%Y-%m-%dT%H")
    if schedule.hour is None or (current.hour, current.minute) < (schedule.hour, schedule.minute):
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
        self.state = load_state()
        if not STATE_FILE.exists():
            self.state = seed_initial_state(datetime.now(timezone.utc))
            log("initial schedule state seeded; already-due legacy tasks will not run twice")

    @staticmethod
    def _start(item: Worker | Schedule) -> subprocess.Popen:
        return subprocess.Popen(item.command, cwd=item.cwd)

    def start_worker(self, worker: Worker) -> None:
        self.workers[worker.name] = self._start(worker)
        self.worker_started_at[worker.name] = time.monotonic()
        log(f"worker started: {worker.name} pid={self.workers[worker.name].pid}")

    def maintain_workers(self) -> None:
        for worker in WORKERS:
            process = self.workers.get(worker.name)
            if process is None:
                self.start_worker(worker)
                continue
            code = process.poll()
            if code is None:
                continue
            elapsed = time.monotonic() - self.worker_started_at.get(worker.name, 0)
            if elapsed < RESTART_DELAY_SECONDS:
                continue
            log(f"worker exited: {worker.name} code={code}; restarting")
            self.start_worker(worker)

    def maintain_schedules(self, now: datetime) -> None:
        for name, (slot, process) in list(self.scheduled.items()):
            code = process.poll()
            if code is None:
                continue
            log(f"scheduled task finished: {name} slot={slot} code={code}")
            self.scheduled.pop(name, None)

        for schedule in SCHEDULES:
            slot = due_slot(schedule, now)
            if not slot or self.state.get(schedule.name) == slot:
                continue
            if schedule.name in self.scheduled:
                continue
            # Save before spawning so a supervisor restart cannot duplicate a run.
            self.state[schedule.name] = slot
            save_state(self.state)
            process = self._start(schedule)
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
