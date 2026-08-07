import datetime
import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from rescuer.core.database import Database
from rescuer.engine.models import FoundFile, RecoverySource
from rescuer.engine.recovery.processor import recover_file
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.exceptions import RecoveryError

log = logging.getLogger("rescuer.engine.recovery")


def _now() -> str:
    return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")


def found_from_row(row, source: RecoverySource | None) -> FoundFile:
    return FoundFile(
        name=row["name"],
        size=int(row["size"] or 0),
        is_deleted=bool(row["is_deleted"]),
        found_by=row["found_by"] or "filesystem",
        fs_type=row["fs_type"] or "",
        ext=row["ext"] or "",
        path=row["path"] or "",
        inode=row["inode"],
        cluster=row["cluster"],
        raw_offset=row["raw_offset"],
        signature_id=row["signature_id"],
        created=row["created_at"],
        modified=row["modified_at"],
        deleted_at=row["deleted_at"],
        score=row["quality_score"],
        confidence=row["confidence"],
        explanation=row["quality_explanation"],
        footer_found=bool(row["footer_found"]),
        file_id=row["id"],
        sha256=row["sha256"],
    )


def source_from_scan(db: Database, scan_id: int) -> RecoverySource | None:
    row = db.query_one(
        "SELECT device_id, mode FROM scans WHERE id = ?", (scan_id,)
    )
    if row is None or not row["device_id"]:
        return None
    from pathlib import Path

    device = row["device_id"]
    if device.lower().startswith("\\\\.\\"):
        return RecoverySource(kind="volume", device_path=device)
    if Path(device).exists():
        if Path(device).is_dir():
            if _is_drive_root(device):
                return RecoverySource(kind="volume", mount_point=device)
            return RecoverySource(kind="folder", mount_point=device)
        return RecoverySource(kind="image", image_path=device)
    return RecoverySource(kind="volume", mount_point=device)


def _is_drive_root(path: str) -> bool:
    import re

    return re.match(r"^[A-Za-z]:[\\/]?$", path) is not None


def enqueue(db: Database, file_ids: list[int], priority: int = 0) -> int:
    """Enqueue file ids, skipping items already queued or in progress."""
    added = 0
    for fid in file_ids:
        existing = db.query_one(
            "SELECT id FROM queue WHERE file_id = ? AND status IN ('queued','processing')",
            (fid,),
        )
        if existing:
            continue
        db.execute(
            "INSERT INTO queue (file_id, priority, status, added_at) VALUES (?, ?, 'queued', ?)",
            (fid, priority, _now()),
        )
        added += 1
    return added


def enqueue_scan(db: Database, scan_id: int, min_score: int = 0) -> int:
    rows = db.query(
        "SELECT id FROM files WHERE scan_id = ? AND COALESCE(quality_score,0) >= ?",
        (scan_id, min_score),
    )
    return enqueue(db, [r["id"] for r in rows])


def queue_stats(db: Database) -> dict:
    counts = {"queued": 0, "processing": 0, "done": 0, "failed": 0, "skipped": 0}
    for row in db.query("SELECT status, COUNT(*) AS n FROM queue GROUP BY status"):
        status = row["status"]
        if status in counts:
            counts[status] = row["n"]
        else:
            counts[status] = row["n"]
    return counts


@dataclass
class ItemOutcome:
    queue_id: int
    file_id: int
    ok: bool
    status: str
    dest_path: str
    bytes_written: int
    hash_match: bool | None
    error: str | None


class QueueSignals(QObject):
    progress = Signal(int, int)
    item_done = Signal(object)
    finished = Signal(int, int)
    failed = Signal(str)


class RecoveryWorker(QThread):
    def __init__(
        self,
        db: Database,
        scan_id: int,
        dest_dir: str,
        registry: SignatureRegistry,
        signals: QueueSignals,
        verify_hash: bool = True,
        cancel_flag: list[bool] | None = None,
        plugins=None,
        restore_original: bool = False,
    ) -> None:
        super().__init__()
        self._db = db
        self._scan_id = scan_id
        self._dest_dir = dest_dir
        self._registry = registry
        self._signals = signals
        self._verify_hash = verify_hash
        self._cancel = cancel_flag if cancel_flag is not None else [False]
        self._plugins = plugins
        self._restore_original = restore_original

    def run(self) -> None:
        source = source_from_scan(self._db, self._scan_id)
        rows = self._db.query(
            "SELECT q.id AS qid, q.file_id AS fid, f.* FROM queue q "
            "JOIN files f ON f.id = q.file_id "
            "WHERE q.status IN ('queued','processing') AND f.scan_id = ? "
            "ORDER BY q.priority DESC, q.added_at ASC",
            (self._scan_id,),
        )
        done = failed = 0
        total = len(rows)
        for row in rows:
            if self._cancel[0]:
                break
            outcome = self._recover_one(row, source)
            self._signals.item_done.emit(outcome)
            self._signals.progress.emit(done + failed, total)
            if outcome.ok:
                done += 1
            else:
                failed += 1
        self._signals.finished.emit(done, failed)

    def _recover_one(self, row, source: RecoverySource | None) -> ItemOutcome:
        file_id = row["fid"]
        if self._plugins is not None:
            self._plugins.emit("recovery_started", file_id=file_id)
        outcome = self._do_recover(row, source)
        if self._plugins is not None:
            self._plugins.emit("recovery_finished", file_id=file_id, ok=outcome.ok)
        return outcome

    def _do_recover(self, row, source: RecoverySource | None) -> ItemOutcome:
        queue_id = row["qid"]
        file_id = row["fid"]
        self._db.execute(
            "UPDATE queue SET status = 'processing' WHERE id = ?", (queue_id,)
        )
        start = _now()
        dest_path = ""
        try:
            if source is None:
                raise RecoveryError("Recovery source unavailable (scan has no device)")
            found = found_from_row(row, source)
            if found.sha256:
                dup = self._db.query_one(
                    "SELECT f2.id FROM recoveries r JOIN files f2 ON f2.id = r.file_id "
                    "WHERE f2.sha256 = ? AND r.status = 'success' AND f2.id != ?",
                    (found.sha256, file_id),
                )
                if dup is not None:
                    self._record(queue_id, file_id, start, "skipped", "", 0, None, "Duplicate content already recovered")
                    return ItemOutcome(queue_id, file_id, True, "skipped", "", 0, None, None)
            result = recover_file(
                found,
                source,
                self._dest_dir,
                verify_hash=self._verify_hash,
                registry=self._registry,
                restore_original=self._restore_original,
            )
            dest_path = result.dest_path
            self._record(
                queue_id, file_id, start, result.status, result.dest_path,
                result.bytes_written, result.hash_match, result.error,
            )
            return ItemOutcome(
                queue_id, file_id, result.ok, result.status, result.dest_path,
                result.bytes_written, result.hash_match, result.error,
            )
        except Exception as exc:
            log.exception("recovery of file %s failed", file_id)
            self._record(queue_id, file_id, start, "failed", "", 0, None, str(exc))
            return ItemOutcome(queue_id, file_id, False, "failed", "", 0, None, str(exc))

    def _record(self, queue_id, file_id, started, status, dest_path, bytes_written, hash_match, error) -> None:
        queue_status = "done" if status == "success" else status
        self._db.execute(
            "UPDATE queue SET status = ?, recovered_at = ? WHERE id = ?",
            (queue_status, _now(), queue_id),
        )
        self._db.execute(
            "UPDATE files SET status = ? WHERE id = ?", (queue_status, file_id)
        )
        self._db.execute(
            "INSERT INTO recoveries (scan_id, file_id, dest_path, status, started_at, "
            "finished_at, bytes_written, hash_match, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._scan_id, file_id, dest_path, status, started,
                _now(), bytes_written, hash_match, error,
            ),
        )


class RecoveryQueue:
    def __init__(self, db: Database, plugins=None) -> None:
        self._db = db
        self._plugins = plugins
        self._worker: RecoveryWorker | None = None
        self._signals = QueueSignals()
        self._cancel: list[bool] = [False]

    @property
    def running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def start(
        self,
        scan_id: int,
        dest_dir: str,
        registry: SignatureRegistry,
        verify_hash: bool = True,
        restore_original: bool = False,
    ) -> None:
        if self.running:
            raise RecoveryError("Recovery queue is already running")
        self._cancel = [False]
        self._worker = RecoveryWorker(
            self._db, scan_id, dest_dir, registry, self._signals,
            verify_hash=verify_hash, cancel_flag=self._cancel,
            plugins=self._plugins, restore_original=restore_original,
        )
        self._worker.start()

    def cancel(self) -> None:
        self._cancel[0] = True
