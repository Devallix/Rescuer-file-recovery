import datetime
import json
import logging

from PySide6.QtCore import QObject, QThread, Signal

from rescuer.core.database import Database
from rescuer.engine.models import FoundFile, ScanConfig
from rescuer.engine.scan.deep import run_deep_scan
from rescuer.engine.scan.partition import run_partition_scan
from rescuer.engine.scan.quick import run_quick_scan
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.exceptions import DeviceAccessError, ScanError

log = logging.getLogger("rescuer.engine.scan")


class ScanSignals(QObject):
    progress = Signal(int, float, str)
    found = Signal(int, int)
    finished = Signal(int)
    cancelled = Signal(int, int)
    failed = Signal(int, str)
    blocked = Signal(int, str)


class ScanWorker(QThread):
    def __init__(
        self,
        db: Database,
        config: ScanConfig,
        scan_id: int,
        registry: SignatureRegistry,
        signals: ScanSignals,
        cancel_flag: list[bool],
        plugins=None,
    ) -> None:
        super().__init__()
        self._db = db
        self._config = config
        self._scan_id = scan_id
        self._registry = registry
        self._signals = signals
        self._cancel = cancel_flag
        self._plugins = plugins

    def run(self) -> None:
        files: list[FoundFile] = []
        try:
            mode = self._config.mode
            self._emit("scan_started", scan_id=self._scan_id, mode=mode)
            if mode == "quick":
                files = run_quick_scan(
                    self._config.source,
                    self._config,
                    progress=self._quick_progress,
                    cancel_flag=self._cancel,
                )
            elif mode in ("deep", "signature"):
                files = run_deep_scan(
                    self._config.source,
                    self._config,
                    self._registry,
                    progress=self._progress,
                    cancel_flag=self._cancel,
                )
            elif mode == "partition":
                files = run_partition_scan(self._config.source, self._config, self._registry)
            elif mode == "recycle":
                from rescuer.engine.scan.recycle import run_recycle_scan

                files = run_recycle_scan(
                    self._config.source,
                    self._config,
                    self._registry,
                    progress=self._recycle_progress,
                    cancel_flag=self._cancel,
                )
            else:
                raise ScanError(f"Unknown scan mode: {mode}")

            if self._cancel and self._cancel[0]:
                # Keep whatever was found before the cancel so the user can
                # still review and recover the partial results.
                inserted = self._persist(files) if files else 0
                self._db.execute(
                    "UPDATE scans SET status='cancelled', finished_at=?, found_count=?, "
                    "sectors_scanned=? WHERE id=?",
                    (_now(), inserted, sum(f.size for f in files), self._scan_id),
                )
                self._emit("scan_finished", scan_id=self._scan_id, count=inserted)
                self._signals.cancelled.emit(self._scan_id, inserted)
                return

            inserted = self._persist(files)
            self._db.execute(
                "UPDATE scans SET status='completed', finished_at=?, found_count=?, "
                "sectors_scanned=? WHERE id=?",
                (_now(), inserted, sum(f.size for f in files), self._scan_id),
            )
            self._emit("scan_finished", scan_id=self._scan_id, count=inserted)
            self._signals.finished.emit(self._scan_id)
        except DeviceAccessError as exc:
            log.warning("scan %s blocked (access denied): %s", self._scan_id, exc)
            self._db.execute(
                "UPDATE scans SET status='failed', finished_at=?, errors_json=? WHERE id=?",
                (_now(), json.dumps([str(exc)]), self._scan_id),
            )
            self._signals.blocked.emit(self._scan_id, str(exc))
        except Exception as exc:
            log.exception("scan %s failed", self._scan_id)
            self._db.execute(
                "UPDATE scans SET status='failed', finished_at=?, errors_json=? WHERE id=?",
                (_now(), json.dumps([str(exc)]), self._scan_id),
            )
            self._signals.failed.emit(self._scan_id, str(exc))

    def _emit(self, event: str, **kwargs) -> None:
        if self._plugins is not None:
            self._plugins.emit(event, **kwargs)

    def _progress(self, scanned: int, total: int, found: int) -> None:
        fraction = scanned / total if total else 0.0
        self._signals.progress.emit(self._scan_id, fraction, "scanning")
        self._signals.found.emit(self._scan_id, found)

    def _quick_progress(self, walked: int, found: int) -> None:
        self._signals.progress.emit(
            self._scan_id,
            0.0,
            f"Scanning… {walked:,} filesystem entries",
        )
        self._signals.found.emit(self._scan_id, found)

    def _recycle_progress(self, processed: int, total: int, found: int) -> None:
        fraction = processed / total if total else 0.0
        phase = f"Scanning Recycle Bin ({processed}/{total} user folders)"
        self._signals.progress.emit(self._scan_id, fraction, phase)
        self._signals.found.emit(self._scan_id, found)

    def _persist(self, files: list[FoundFile]) -> int:
        if not files:
            return 0
        from rescuer.engine.quality.scorer import QualityScorer

        scorer = QualityScorer()
        batch = []
        for f in files:
            sig = self._registry.get(f.signature_id) if f.signature_id else None
            quality = scorer.score(f, sig)
            f.score = quality.score
            f.confidence = quality.confidence
            f.explanation = " ".join(quality.explanation)
            batch.append((
                self._scan_id, f.name, f.ext, f.path, f.size,
                int(f.is_deleted), f.created, f.deleted_at, f.modified,
                f.fs_type, f.cluster, f.inode, f.found_by, f.raw_offset,
                f.signature_id, int(f.footer_found), quality.score,
                quality.confidence, " ".join(quality.explanation),
                sig.category if sig else None,
            ))
        self._db.executemany(
            "INSERT INTO files (scan_id, name, ext, path, size, is_deleted, "
            "created_at, deleted_at, modified_at, fs_type, cluster, inode, "
            "found_by, raw_offset, signature_id, footer_found, quality_score, "
            "confidence, quality_explanation, category, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new')",
            batch,
        )
        rows = self._db.query(
            "SELECT id, name FROM files WHERE scan_id = ?", (self._scan_id,)
        )
        for row in rows:
            self._emit("found", file_id=row["id"], name=row["name"])
        return len(batch)


def _now() -> str:
    return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")


class ScanController(QObject):
    progress = Signal(int, float, str)
    found = Signal(int, int)
    finished = Signal(int)
    cancelled = Signal(int, int)
    failed = Signal(int, str)
    blocked = Signal(int, str)

    def __init__(self, db: Database, plugins=None) -> None:
        super().__init__()
        self._db = db
        self._plugins = plugins
        self._workers: dict[int, ScanWorker] = {}
        self._cancel_flags: dict[int, list[bool]] = {}
        self._idle_callbacks: list = []
        self._signals = ScanSignals()
        self._signals.progress.connect(self.progress)
        self._signals.found.connect(self.found)
        self._signals.finished.connect(self.finished)
        self._signals.cancelled.connect(self.cancelled)
        self._signals.failed.connect(self.failed)
        self._signals.blocked.connect(self.blocked)

    @property
    def running(self) -> bool:
        return any(w.isRunning() for w in self._workers.values())

    @property
    def active_scan_ids(self) -> list[int]:
        return [sid for sid, worker in self._workers.items() if worker.isRunning()]

    def is_running(self, scan_id: int) -> bool:
        worker = self._workers.get(scan_id)
        return bool(worker and worker.isRunning())

    def when_idle(self, callback) -> None:
        """Invoke ``callback`` (on the GUI thread) once no scan worker is running."""
        if self.running:
            self._idle_callbacks.append(callback)
        else:
            callback()

    def create_scan(self, config: ScanConfig) -> int:
        device_id = config.source.raw_path() if config.source else ""
        return self._db.execute(
            "INSERT INTO scans (device_id, mode, status, filters_json, started_at, config_json) "
            "VALUES (?, ?, 'running', ?, ?, ?)",
            (
                device_id,
                config.mode,
                json.dumps(config.filters or {}),
                _now(),
                json.dumps({"workers": config.workers}),
            ),
        )

    def start(self, config: ScanConfig, registry: SignatureRegistry, scan_id: int | None = None) -> int:
        if config.source is None:
            raise ScanError("No recovery source selected")
        scan_id = scan_id or self.create_scan(config)
        cancel = [False]
        worker = ScanWorker(self._db, config, scan_id, registry, self._signals, cancel, self._plugins)
        self._workers[scan_id] = worker
        self._cancel_flags[scan_id] = cancel
        worker.finished.connect(lambda: self._on_worker_exit(scan_id))
        worker.start()
        return scan_id

    def cancel(self, scan_id: int | None = None) -> None:
        if scan_id is None:
            for flag in self._cancel_flags.values():
                flag[0] = True
        else:
            flag = self._cancel_flags.get(scan_id)
            if flag is not None:
                flag[0] = True

    def cancel_all(self) -> None:
        self.cancel()

    def _on_worker_exit(self, scan_id: int) -> None:
        self._workers.pop(scan_id, None)
        self._cancel_flags.pop(scan_id, None)
        if not self.running and self._idle_callbacks:
            callbacks, self._idle_callbacks = self._idle_callbacks, []
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    log.exception("idle callback failed")
