import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import pytest

from fixtures.fat12_builder import make_fat12_image
from rescuer.engine.models import RecoverySource, ScanConfig
from rescuer.engine.partition.analyzer import analyze, analyze_boot_area
from rescuer.engine.recovery.processor import recover_file
from rescuer.engine.scan.deep import run_deep_scan
from rescuer.engine.scan.quick import run_quick_scan
from rescuer.engine.signatures.registry import SignatureRegistry


@pytest.fixture(scope="session")
def registry():
    return SignatureRegistry.load()


@pytest.fixture()
def fat_image(tmp_path: Path) -> str:
    path = str(tmp_path / "fixture.img")
    make_fat12_image(path)
    return path


def _source(path: str) -> RecoverySource:
    return RecoverySource(kind="image", image_path=path, label="fixture")


def test_registry_loads(registry):
    assert len(registry.signatures) >= 70
    assert registry.get("pdf") is not None
    assert registry.get("jpeg").footer is not None


def test_quick_scan_finds_deleted(fat_image):
    source = _source(fat_image)
    files = run_quick_scan(source, ScanConfig(mode="quick", source=source))
    by_name = {f.name.upper(): f for f in files}
    assert "HELLO.TXT" in by_name
    assert not by_name["HELLO.TXT"].is_deleted
    assert "PIC.PNG" in by_name
    deleted = [f for f in files if f.is_deleted]
    assert any("OST.JPG" in f.name.upper() for f in deleted)
    assert any("ONE.TXT" in f.name.upper() for f in deleted)


def test_quick_scan_recovers_content(fat_image, tmp_path):
    source = _source(fat_image)
    files = run_quick_scan(source, ScanConfig(mode="quick", source=source))
    hello = next(f for f in files if f.name.upper() == "HELLO.TXT")
    result = recover_file(hello, source, str(tmp_path / "out"), verify_hash=False)
    assert result.ok
    assert Path(result.dest_path).read_bytes().startswith(b"Hello from Rescuer")


def test_deep_scan_carves(fat_image, registry):
    source = _source(fat_image)
    files = run_deep_scan(source, ScanConfig(mode="deep", source=source), registry)
    sigs = {f.signature_id for f in files}
    assert "jpeg" in sigs
    assert "png" in sigs
    jpeg = next(f for f in files if f.signature_id == "jpeg")
    assert jpeg.size >= 400
    assert jpeg.footer_found


def test_deep_scan_recovery(fat_image, registry, tmp_path):
    source = _source(fat_image)
    files = run_deep_scan(source, ScanConfig(mode="deep", source=source), registry)
    jpeg = next(f for f in files if f.signature_id == "jpeg")
    result = recover_file(jpeg, source, str(tmp_path / "out"), verify_hash=False, registry=registry)
    assert result.ok
    data = Path(result.dest_path).read_bytes()
    assert data[:3] == b"\xff\xd8\xff"
    assert data[-2:] == b"\xff\xd9"


def test_partition_analyzer(fat_image):
    size = os.path.getsize(fat_image)
    result = analyze(fat_image, size)
    assert result.table_type == "mbr"
    assert result.partitions == []
    assert analyze_boot_area(fat_image, size) in ("fat12", "fat16", "fat")


def test_partition_analyzer_disk(tmp_path: Path):
    from fixtures.fat12_builder import make_partitioned_image

    disk = str(tmp_path / "disk.img")
    make_partitioned_image(disk, partition_start_lba=63)
    size = os.path.getsize(disk)
    result = analyze(disk, size)
    assert result.table_type == "mbr"
    assert len(result.partitions) == 1
    part = result.partitions[0]
    assert part.start_lba == 63
    assert part.fs_type in ("fat12", "fat16", "fat")
