from datetime import datetime, timezone
import os
import stat

from scheduler import casinoinbot


def test_casinoinbot_inventory_matches_pythonanywhere_tasks():
    assert len(casinoinbot.WORKERS) == 3
    assert len(casinoinbot.SCHEDULES) == 7
    assert {item.name for item in casinoinbot.WORKERS} == {
        "email_monitor", "casino_news_watch", "telegram_ingest"
    }
    assert {item.name for item in casinoinbot.SCHEDULES} >= {
        "law_sync", "dart_sync", "localization_translation"
    }


def test_daily_due_slot_is_once_per_utc_day_and_catches_up():
    schedule = next(item for item in casinoinbot.SCHEDULES if item.name == "law_sync")
    assert casinoinbot.due_slot(schedule, datetime(2026, 8, 6, 11, 59, tzinfo=timezone.utc)) is None
    assert casinoinbot.due_slot(schedule, datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)) == "2026-08-06"
    assert casinoinbot.due_slot(schedule, datetime(2026, 8, 6, 17, 0, tzinfo=timezone.utc)) == "2026-08-06"


def test_hourly_due_slot_changes_each_hour_after_minute_30():
    schedule = next(item for item in casinoinbot.SCHEDULES if item.name == "dart_sync")
    assert casinoinbot.due_slot(schedule, datetime(2026, 8, 6, 12, 29, tzinfo=timezone.utc)) is None
    assert casinoinbot.due_slot(schedule, datetime(2026, 8, 6, 12, 30, tzinfo=timezone.utc)) == "2026-08-06T12"
    assert casinoinbot.due_slot(schedule, datetime(2026, 8, 6, 13, 45, tzinfo=timezone.utc)) == "2026-08-06T13"


def test_initial_state_marks_only_already_due_slots(monkeypatch, tmp_path):
    monkeypatch.setattr(casinoinbot, "STATE_DIR", tmp_path)
    monkeypatch.setattr(casinoinbot, "STATE_FILE", tmp_path / "state.json")
    state = casinoinbot.seed_initial_state(datetime(2026, 8, 6, 17, 35, tzinfo=timezone.utc))
    assert state["law_sync"] == "2026-08-06"
    assert state["dart_sync"] == "2026-08-06T17"
    assert "salary_sync" not in state
    if os.name != "nt":
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
        assert stat.S_IMODE((tmp_path / "state.json").stat().st_mode) == 0o600


def test_failed_schedule_spawn_is_not_marked_complete(monkeypatch, tmp_path):
    schedule = next(item for item in casinoinbot.SCHEDULES if item.name == "law_sync")
    monkeypatch.setattr(casinoinbot, "SCHEDULES", (schedule,))
    monkeypatch.setattr(casinoinbot, "STATE_DIR", tmp_path)
    monkeypatch.setattr(casinoinbot, "STATE_FILE", tmp_path / "state.json")
    supervisor = casinoinbot.Supervisor.__new__(casinoinbot.Supervisor)
    supervisor.scheduled = {}
    supervisor.settings = {"law_sync": {"enabled": True}}
    supervisor.state = {}
    supervisor.last_error_alert = {}
    supervisor._start = lambda *_args: (_ for _ in ()).throw(OSError("missing executable"))
    supervisor._notify_error = lambda *_args: None

    supervisor.maintain_schedules(datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc))

    assert supervisor.state == {}
    assert not (tmp_path / "state.json").exists()


def test_invalid_saved_task_number_falls_back_to_default():
    setting = casinoinbot.automation_settings._validated(
        "email_monitor", {"interval_minutes": "broken"}
    )
    assert setting["interval_minutes"] == 5
