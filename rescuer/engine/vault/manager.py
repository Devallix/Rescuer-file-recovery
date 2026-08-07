import datetime
import json
import logging

from rescuer.core.database import Database

log = logging.getLogger("rescuer.engine.vault")


def _now() -> str:
    return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")


def create_vault(db: Database, folder: str, metadata: dict | None = None) -> int:
    return db.execute(
        "INSERT INTO vault (folder, added_at, metadata_json, status) VALUES (?, ?, ?, 'active')",
        (folder, _now(), json.dumps(metadata or {})),
    )


def list_vaults(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM vault WHERE status = 'active' ORDER BY added_at DESC")
    result = []
    for row in rows:
        data = dict(row)
        data["metadata"] = json.loads(data["metadata_json"]) if data.get("metadata_json") else {}
        result.append(data)
    return result


def get_vault(db: Database, vault_id: int) -> dict | None:
    row = db.query_one("SELECT * FROM vault WHERE id = ? AND status = 'active'", (vault_id,))
    if row is None:
        return None
    data = dict(row)
    data["metadata"] = json.loads(data["metadata_json"]) if data.get("metadata_json") else {}
    return data


def delete_vault(db: Database, vault_id: int) -> None:
    db.execute("UPDATE vault SET status = 'deleted' WHERE id = ?", (vault_id,))
