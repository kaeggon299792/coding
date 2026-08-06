from deployment import sync_tracked_source


def test_deployment_source_sync_excludes_runtime_paths():
    safe_source_path = sync_tracked_source.safe_source_path
    assert safe_source_path("dashboard/templates/removed.html")
    assert safe_source_path("dashboard/static/css/removed.css")
    assert not safe_source_path("dashboard/.env")
    assert not safe_source_path("dashboard/dashboard.db")
    assert not safe_source_path("dashboard/logs/task.log")
    assert not safe_source_path("dashboard/static/uploads/profile.png")
    assert not safe_source_path("dashboard/data/diary_images/private.png")
    assert not safe_source_path("../outside")


def test_deployment_source_sync_removes_only_disappeared_source(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard"
    stale_source = dashboard / "templates" / "removed.html"
    runtime_log = dashboard / "logs" / "task.log"
    current_source = dashboard / "templates" / "current.html"
    for path in (stale_source, runtime_log, current_source):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")

    revisions = {
        "old": {
            "dashboard/templates/removed.html",
            "dashboard/templates/current.html",
            "dashboard/logs/task.log",
        },
        "new": {"dashboard/templates/current.html"},
    }
    monkeypatch.setattr(
        sync_tracked_source,
        "tracked_paths",
        lambda _repo, revision: revisions[revision],
    )

    removed = sync_tracked_source.remove_disappeared(tmp_path, "old", "new")

    assert removed == ["dashboard/templates/removed.html"]
    assert not stale_source.exists()
    assert runtime_log.exists()
    assert current_source.exists()
