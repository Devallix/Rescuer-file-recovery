import os
from pathlib import Path

import pytest

from rescuer.core.database import Database
from rescuer.engine.imaging.dumper import create_image, verify_image
from rescuer.engine.models import RecoverySource, ScanConfig
from rescuer.engine.recovery.processor import same_volume
from rescuer.engine.reports.generator import generate
from rescuer.engine.session import manager as sessions
from rescuer.engine.signatures.registry import SignatureRegistry


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db", Path("rescuer/data/migrations"))


@pytest.fixture()
def registry() -> SignatureRegistry:
    return SignatureRegistry.load()


@pytest.fixture(scope="module")
def fat_image() -> str:
    from fixtures.fat12_builder import make_fat12_image

    from rescuer.paths import Paths

    Paths.ensure_dirs()
    path = os.path.join(Paths.cache_dir, "phase4_fixture.img")
    make_fat12_image(path)
    return path


@pytest.fixture()
def scan_id(db: Database, registry: SignatureRegistry, fat_image: str) -> int:
    from rescuer.engine.scan.controller import ScanSignals, ScanWorker

    source = RecoverySource(kind="image", image_path=fat_image, size=os.path.getsize(fat_image))
    sid = db.execute("INSERT INTO scans (device_id, mode, status) VALUES (?, 'deep', 'running')", (fat_image,))
    ScanWorker(db, ScanConfig(mode="deep", source=source), sid, registry, ScanSignals(), [False]).run()
    return sid


def test_same_volume_guard():
    vol = RecoverySource(kind="volume", mount_point="C:\\")
    assert same_volume(vol, "C:\\Users\\x") is True
    assert same_volume(vol, "D:\\out") is False
    img = RecoverySource(kind="image", image_path="z.img")
    assert same_volume(img, "C:\\out") is False


def test_cancel_persists_partial_results(db: Database, monkeypatch):
    from rescuer.engine.models import FoundFile, ScanConfig
    from rescuer.engine.scan.controller import ScanSignals, ScanWorker

    source = RecoverySource(kind="image", image_path="x.img", size=1000)
    config = ScanConfig(mode="quick", source=source)

    def fake_quick_scan(source, config, progress=None, cancel_flag=None):
        return [
            FoundFile(name="a.txt", size=10, is_deleted=True, found_by="filesystem", path="/a.txt", inode=1),
            FoundFile(name="b.txt", size=20, is_deleted=True, found_by="filesystem", path="/b.txt", inode=2),
        ]

    monkeypatch.setattr("rescuer.engine.scan.controller.run_quick_scan", fake_quick_scan)

    sid = db.execute("INSERT INTO scans (device_id, mode, status) VALUES (?, 'quick', 'running')", ("x.img",))
    signals = ScanSignals()
    outcomes: list = []
    signals.cancelled.connect(lambda s, c: outcomes.append((s, c)))
    ScanWorker(db, config, sid, None, signals, [True]).run()

    assert outcomes and outcomes[0] == (sid, 2)
    rows = db.query("SELECT name FROM files WHERE scan_id = ?", (sid,))
    assert {r["name"] for r in rows} == {"a.txt", "b.txt"}
    status = db.query("SELECT status FROM scans WHERE id = ?", (sid,))[0]["status"]
    assert status == "cancelled"


def test_imaging_copy_roundtrip(tmp_path: Path, fat_image: str):
    dest = str(tmp_path / "copy.img")
    result = create_image(fat_image, dest)
    assert result.size > 0
    assert result.mb_per_sec >= 0
    assert verify_image(dest, expected_size=os.path.getsize(fat_image))
    assert os.path.getsize(dest) == os.path.getsize(fat_image)


def test_imaging_progress_and_cancel(tmp_path: Path, fat_image: str):
    progress_calls: list[tuple[int, int]] = []
    dest = str(tmp_path / "cancel.img")

    def prog(done, total):
        progress_calls.append((done, total))

    create_image(fat_image, dest, progress=prog)
    assert progress_calls and progress_calls[-1][0] == os.path.getsize(fat_image)


def test_imaging_source_normalization():
    from rescuer.engine.imaging.dumper import _normalize_source

    assert _normalize_source("C:") == r"\\.\C:"
    assert _normalize_source("C:\\") == r"\\.\C:"
    assert _normalize_source("C:/") == r"\\.\C:"
    assert _normalize_source(r"\\.\D:") == r"\\.\D:"
    assert _normalize_source(r"C:\Users\x\file.img") == r"C:\Users\x\file.img"
    assert _normalize_source("") == ""


def test_imaging_raw_read_eof(monkeypatch):
    import win32file

    from rescuer.engine.imaging.dumper import _read_raw

    class FakeHandle:
        pass

    calls: list[int] = []

    def fake_read_file(handle, size):
        calls.append(size)
        if len(calls) == 1:
            return (0, b"x" * size)
        return (38, b"")

    monkeypatch.setattr(win32file, "ReadFile", fake_read_file)
    assert _read_raw(FakeHandle(), 1024) == b"x" * 1024
    assert _read_raw(FakeHandle(), 1024) == b""


def test_imaging_mount_point_size():
    from rescuer.engine.imaging.dumper import image_size

    assert image_size("C:\\") > 0
    assert image_size("C:\\") != 8192


def test_imaging_controller_roundtrip(qtbot, tmp_path: Path, fat_image: str):
    from rescuer.engine.imaging.controller import ImagingController

    ctl = ImagingController()
    with qtbot.waitSignal(ctl.finished, timeout=10000) as blocker:
        ctl.start(fat_image, str(tmp_path / "ctl.img"))
    result = blocker.args[0]
    assert result.size == os.path.getsize(fat_image)
    assert os.path.exists(result.path)


def test_imaging_worker_cancel(tmp_path: Path, fat_image: str):
    from rescuer.engine.imaging.controller import ImagingSignals, ImagingWorker

    signals = ImagingSignals()
    outcomes: list = []
    signals.finished.connect(lambda r: outcomes.append(("ok", r)))
    signals.failed.connect(lambda e: outcomes.append(("err", e)))
    worker = ImagingWorker(fat_image, str(tmp_path / "cancelled.img"), signals, [True])
    worker.run()
    assert outcomes and outcomes[0][0] == "err"
    assert "cancel" in outcomes[0][1].lower()


def test_session_create_resume_delete(db: Database, scan_id: int):
    sid = sessions.create_session(db, "First recovery", scan_id)
    assert sid > 0
    listed = sessions.list_sessions(db)
    assert any(s["id"] == sid for s in listed)
    resumed = sessions.resume_session(db, sid)
    assert resumed["id"] == sid
    assert resumed["snapshot"]["scan"]["id"] == scan_id
    sessions.delete_session(db, sid)
    assert sessions.get_session(db, sid) is None


def test_reports_generated(db: Database, scan_id: int, tmp_path: Path):
    html = generate(db, scan_id, str(tmp_path), "html")
    assert os.path.exists(html)
    assert "Rescuer" in Path(html).read_text(encoding="utf-8")

    csv_path = generate(db, scan_id, str(tmp_path), "csv")
    assert os.path.exists(csv_path)
    assert Path(csv_path).read_text(encoding="utf-8").count("\n") >= 1

    pdf_path = generate(db, scan_id, str(tmp_path), "pdf")
    assert os.path.exists(pdf_path)
    assert Path(pdf_path).read_bytes()[:5] == b"%PDF-"


def test_queue_enqueue_and_stats(db: Database, scan_id: int):
    from rescuer.engine.recovery.queue import enqueue_scan, queue_stats

    added = enqueue_scan(db, scan_id, min_score=0)
    assert added >= 1
    stats = queue_stats(db)
    assert stats["queued"] >= 1
    dup = enqueue_scan(db, scan_id, min_score=0)
    assert dup == 0


def test_queue_worker_recovers_files(db: Database, scan_id: int, registry: SignatureRegistry, tmp_path: Path, fat_image: str):
    from rescuer.engine.recovery.queue import QueueSignals, RecoveryWorker, enqueue_scan

    enqueue_scan(db, scan_id, min_score=0)
    outcomes: list = []
    signals = QueueSignals()
    signals.item_done.connect(lambda o: outcomes.append(o))
    worker = RecoveryWorker(db, scan_id, str(tmp_path / "out"), registry, signals, verify_hash=False)
    worker.run()
    assert outcomes
    assert any(o.ok for o in outcomes)
    recovered = [o for o in outcomes if o.ok]
    assert recovered
    assert os.path.exists(recovered[0].dest_path)
    stats = __import__("rescuer.engine.recovery.queue", fromlist=["queue_stats"]).queue_stats(db)
    assert stats["done"] >= 1
