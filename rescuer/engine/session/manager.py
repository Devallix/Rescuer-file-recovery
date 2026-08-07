import datetime
import json

from rescuer.core.database import Database


def _now() -> str:
    return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")


def _snapshot(db: Database, scan_id: int) -> dict:
    scan = db.query_one(
        "SELECT id, device_id, mode, started_at, finished_at, found_count "
        "FROM scans WHERE id = ?",
        (scan_id,),
    )
    if scan is None:
        return {"scan": None, "counts": {}, "top": []}
    counts = {
        row["category"] or "unknown": row["n"]
        for row in db.query(
            "SELECT category, COUNT(*) AS n FROM files WHERE scan_id = ? GROUP BY category",
            (scan_id,),
        )
    }
    top = [
        {"name": row["name"], "score": row["quality_score"], "size": row["size"], "ext": row["ext"]}
        for row in db.query(
            "SELECT name, quality_score, size, ext FROM files WHERE scan_id = ? "
            "ORDER BY quality_score DESC LIMIT 20",
            (scan_id,),
        )
    ]
    return {"scan": dict(scan), "counts": counts, "top": top}


def create_session(db: Database, name: str, scan_id: int | None = None) -> int:
    snapshot = json.dumps(_snapshot(db, scan_id)) if scan_id is not None else None
    return db.execute(
        "INSERT INTO sessions (name, scan_id, snapshot_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (name, scan_id, snapshot, _now()),
    )


def list_sessions(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM sessions ORDER BY created_at DESC")
    return [dict(r) for r in rows]


def get_session(db: Database, session_id: int) -> dict | None:
    row = db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if row is None:
        return None
    data = dict(row)
    data["snapshot"] = json.loads(data["snapshot_json"]) if data.get("snapshot_json") else {}
    return data


def resume_session(db: Database, session_id: int) -> dict:
    session = get_session(db, session_id)
    if session is None:
        raise ValueError(f"No session with id {session_id}")
    db.execute(
        "UPDATE sessions SET resumed_at = ? WHERE id = ?", (_now(), session_id)
    )
    return session


def delete_session(db: Database, session_id: int) -> None:
    db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def session_recoverable_count(db: Database, session_id: int) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM queue q "
        "JOIN files f ON f.id = q.file_id "
        "JOIN sessions s ON s.scan_id = f.scan_id "
        "WHERE s.id = ? AND q.status IN ('queued','processing')",
        (session_id,),
    )
    return int(row["n"]) if row else 0
