import os
from pathlib import Path

import pytest

from rescuer.core.database import Database
from rescuer.engine.models import RecoverySource, ScanConfig
from rescuer.engine.scan.controller import ScanController
from rescuer.engine.search.assistant import SmartAssistant
from rescuer.engine.search.engine import FileSearch, parse_tokens
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.paths import Paths


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db", Path("rescuer/data/migrations"))


@pytest.fixture()
def registry() -> SignatureRegistry:
    return SignatureRegistry.load()


@pytest.fixture(scope="module")
def fat_image() -> str:
    from fixtures.fat12_builder import make_fat12_image

    Paths.ensure_dirs()
    path = os.path.join(Paths.cache_dir, "search_fixture.img")
    make_fat12_image(path)
    return path


def test_parse_tokens():
    parsed = parse_tokens('photos ext:jpg deleted:yes min:70 "sunday trip"')
    assert parsed["ext"] == "jpg"
    assert parsed["deleted"] is True
    assert parsed["min_score"] == 70
    assert "sunday trip" in parsed["terms"]


def test_search_filters(db: Database, registry: SignatureRegistry, fat_image: str):
    from rescuer.engine.scan.controller import ScanWorker, ScanSignals
    from rescuer.engine.models import ScanConfig

    Paths.ensure_dirs()
    source = RecoverySource(kind="image", image_path=fat_image, size=os.path.getsize(fat_image))
    scan_id = db.execute(
        "INSERT INTO scans (device_id, mode, status) VALUES (?, 'deep', 'running')",
        (fat_image,),
    )
    signals = ScanSignals()
    worker = ScanWorker(db, ScanConfig(mode="deep", source=source), scan_id, registry, signals, [False])
    worker.run()

    search = FileSearch(db)
    all_rows = search.search(scan_id=scan_id)
    assert all_rows

    by_ext = search.search(scan_id=scan_id, ext="jpg")
    assert by_ext
    assert all(r["ext"].lstrip(".").lower() == "jpg" for r in by_ext)

    deleted = search.search(scan_id=scan_id, deleted=True)
    assert all(r["is_deleted"] == 1 for r in deleted)

    scored = search.search(scan_id=scan_id, min_score=50)
    assert all((r["quality_score"] or 0) >= 50 for r in scored)

    categories = {r["category"] for r in all_rows if r["category"]}
    assert categories, "category should be populated by migration+persist"


def test_search_natural_language(db: Database, registry: SignatureRegistry, fat_image: str):
    from rescuer.engine.scan.controller import ScanSignals, ScanWorker

    source = RecoverySource(kind="image", image_path=fat_image, size=os.path.getsize(fat_image))
    scan_id = db.execute("INSERT INTO scans (device_id, mode, status) VALUES (?, 'deep', 'running')", (fat_image,))
    ScanWorker(db, ScanConfig(mode="deep", source=source), scan_id, registry, ScanSignals(), [False]).run()

    assistant = SmartAssistant(FileSearch(db))
    suggestion = assistant.interpret("find deleted photos")
    assert suggestion.filters.get("deleted") is True
    assert suggestion.filters.get("category") == "photos"
    assert suggestion.query

    results = assistant.apply("deleted photos", scan_id=scan_id)
    for r in results:
        assert r["is_deleted"] == 1
        if r["category"]:
            assert r["category"] == "photos"

    suggestions = assistant.suggest("photos")
    assert any(s.label.lower().find("photos") != -1 for s in suggestions)


def test_migration_002_adds_category_column(db: Database):
    cols = {r["name"] for r in db.query("PRAGMA table_info(files)")}
    assert "category" in cols


def test_scan_controller_runs_multiple_scans_in_parallel(qtbot, db: Database, registry: SignatureRegistry):
    import threading

    from rescuer.engine.scan.controller import ScanController

    gate = threading.Event()
    sources = []

    def fake_quick_scan(source, config, progress=None, cancel_flag=None):
        sources.append(source)
        gate.wait(10)
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("rescuer.engine.scan.controller.run_quick_scan", fake_quick_scan)

    try:
        ctl = ScanController(db)
        src_a = RecoverySource(kind="volume", mount_point="C:\\", label="A", fs_type="NTFS", size=0)
        src_b = RecoverySource(kind="volume", mount_point="D:\\", label="B", fs_type="NTFS", size=0)
        sid_a = ctl.start(ScanConfig(mode="quick", source=src_a), registry)
        sid_b = ctl.start(ScanConfig(mode="quick", source=src_b), registry)

        qtbot.waitUntil(lambda: len(sources) == 2, timeout=10000)
        assert ctl.running
        assert sorted(ctl.active_scan_ids) == sorted([sid_a, sid_b])

        gate.set()
        qtbot.waitUntil(lambda: not ctl.running, timeout=15000)
        assert len(sources) == 2
        assert ctl.active_scan_ids == []
    finally:
        gate.set()
        monkeypatch.undo()
