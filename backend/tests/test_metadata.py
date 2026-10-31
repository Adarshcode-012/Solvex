from memory import metadata


def test_metadata_uses_wal_and_isolates_users(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "DB_PATH", str(tmp_path / "metadata.sqlite3"))

    metadata.update_procedure("guest_A", "coder", "Use fast I/O")
    metadata.record_event("guest_A", "solve_complete", {"passed": True})

    assert metadata.get_procedure("guest_A", "coder", "default") == "Use fast I/O"
    assert metadata.get_procedure("guest_B", "coder", "default") == "default"
    assert len(metadata.list_events("guest_A")) == 1
    assert metadata.list_events("guest_B") == []

    with metadata.connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"