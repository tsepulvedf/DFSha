"""Solo capacidad SQLite local; todavía no es el MetadataStore del DFS."""
import sqlite3

import pytest


def test_sqlite_persistence_and_rollback_without_etcd(tmp_path):
    path = tmp_path / "capability.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE probe (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO probe VALUES (?, ?)", ("owned", "before"))
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                db.execute("UPDATE probe SET value = 'uncommitted'")
                db.execute("INSERT INTO probe VALUES ('owned', 'duplicate')")
        assert db.execute("SELECT value FROM probe").fetchone() == ("before",)
