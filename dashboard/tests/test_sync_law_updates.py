from scheduler import sync_law_updates


def test_ensure_mst_refreshes_saved_version(monkeypatch):
    saved = []
    law_row = {"law_name": "관광진흥법", "law_id": "1", "mst": "100"}
    monkeypatch.setattr(
        sync_law_updates.law_client,
        "search_law",
        lambda _name: {
            "ok": True,
            "candidates": [
                {"law_name": "관광진흥법 시행령", "law_id": "2", "mst": "999"},
                {"law_name": "관광진흥법", "law_id": "1", "mst": "101"},
            ],
        },
    )
    monkeypatch.setattr(
        sync_law_updates.queries,
        "upsert_monitored_law",
        lambda connection, law_name, law_id=None, mst=None: saved.append(
            (connection, law_name, law_id, mst)
        ),
    )

    assert sync_law_updates._ensure_mst("db", law_row) == "101"
    assert saved == [("db", "관광진흥법", "1", "101")]


def test_ensure_mst_keeps_saved_version_when_search_fails(monkeypatch):
    monkeypatch.setattr(
        sync_law_updates.law_client,
        "search_law",
        lambda _name: {"ok": False, "error": "timeout"},
    )

    assert sync_law_updates._ensure_mst(
        "db", {"law_name": "관광진흥법", "mst": "100"}
    ) == "100"
