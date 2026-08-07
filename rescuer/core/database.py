import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from rescuer.exceptions import DatabaseError


class Database:
    def __init__(self, db_path: Path, migrations_dir: Path) -> None:
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_pragmas()
        self._migrate()

    def _init_pragmas(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode = WAL")
            cur.execute("PRAGMA foreign_keys = ON")
            cur.execute("PRAGMA synchronous = NORMAL")
            cur.execute("PRAGMA busy_timeout = 15000")

    def _migrate(self) -> None:
        migrations = sorted(self.migrations_dir.glob("*.sql"))
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {row["version"] for row in cur.execute("SELECT version FROM schema_migrations")}
            for m in migrations:
                if m.name in applied:
                    continue
                self._conn.execute("BEGIN")
                try:
                    cur.executescript(m.read_text(encoding="utf-8"))
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (?)", (m.name,)
                    )
                    self._conn.commit()
                except Exception as exc:
                    self._conn.rollback()
                    raise DatabaseError(f"Migration {m.name} failed: {exc}") from exc

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            try:
                cur = self._conn.cursor()
                cur.execute(sql, params)
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.Error as exc:
                raise DatabaseError(str(exc)) from exc

    def executemany(self, sql: str, seq_of_params) -> None:
        with self._lock:
            try:
                self._conn.executemany(sql, seq_of_params)
                self._conn.commit()
            except sqlite3.Error as exc:
                raise DatabaseError(str(exc)) from exc

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetchall()
            except sqlite3.Error as exc:
                raise DatabaseError(str(exc)) from exc

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class Config:
    DEFAULTS: dict[str, Any] = {
        "appearance.theme": "dark",
        "appearance.reduce_motion": False,
        "appearance.smart_effects": True,
        "scan.default_mode": "quick",
        "scan.show_deleted_only": False,
        "scan.verify_hashes": True,
        "recovery.safe_mode": True,
        "logging.level": "INFO",
        "general.launch_minimized": False,
        "general.check_updates": True,
        "updates.endpoint": "https://api.github.com/repos/rescuer-app/rescuer/releases/latest",
        "updates.channel": "stable",
        "signatures.custom_dir": "",
    }

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        rows = self._db.query("SELECT key, value FROM settings")
        stored = {row["key"]: json.loads(row["value"]) for row in rows}
        self._cache = {**self.DEFAULTS, **stored}

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._cache:
            return self._cache[key]
        if default is not None:
            return default
        return self.DEFAULTS.get(key)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def all(self) -> dict[str, Any]:
        return dict(self._cache)
