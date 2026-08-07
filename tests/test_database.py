import json
from pathlib import Path

from rescuer.core.database import Config, Database
from rescuer.exceptions import DatabaseError


def test_migrations_apply(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db", Path("rescuer/data/migrations"))
    rows = db.query("SELECT version FROM schema_migrations")
    versions = [r["version"] for r in rows]
    expected = sorted(p.name for p in Path("rescuer/data/migrations").glob("*.sql"))
    assert versions == expected
    db.close()


def test_tables_created(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db", Path("rescuer/data/migrations"))
    rows = db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    )
    names = {r["name"] for r in rows}
    expected = {"drives", "scans", "files", "queue", "recoveries", "sessions",
                "vault", "reports", "settings", "events"}
    assert expected <= names
    db.close()


def test_insert_and_query(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db", Path("rescuer/data/migrations"))
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("a", "1"))
    row = db.query_one("SELECT key, value FROM settings WHERE key = ?", ("a",))
    assert row["value"] == "1"
    db.close()


def test_foreign_key_cascade(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db", Path("rescuer/data/migrations"))
    scan_id = db.execute(
        "INSERT INTO scans (mode, status) VALUES ('quick', 'completed')"
    )
    db.execute(
        "INSERT INTO files (scan_id, name) VALUES (?, 'x.txt')", (scan_id,)
    )
    db.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
    rows = db.query("SELECT * FROM files WHERE scan_id = ?", (scan_id,))
    assert rows == []
    db.close()


def test_config_defaults_and_set(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db", Path("rescuer/data/migrations"))
    config = Config(db)
    assert config.get("appearance.theme") == "dark"
    config.set("appearance.theme", "light")
    config2 = Config(db)
    assert config2.get("appearance.theme") == "light"
    db.close()
