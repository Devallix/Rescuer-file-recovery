import datetime
import os
import struct
from pathlib import Path

import pytest

from rescuer.core.database import Database
from rescuer.engine.models import RecoverySource
from rescuer.engine.recycle.parser import (
    expand_container,
    find_recycle_items,
    is_container,
    parse_filetime,
    parse_info_file,
    read_item,
    read_item_reader,
)
from rescuer.engine.recovery.processor import recover_file
from rescuer.engine.recovery.queue import source_from_scan


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db", Path("rescuer/data/migrations"))


def _build_info(path: str, original: str, size: int, deleted: datetime.datetime) -> None:
    with open(path, "wb") as fh:
        fh.write(b"\x01\x00\x00\x00\x00\x00\x00\x00")
        fh.write(struct.pack("<Q", size))
        fh.write(struct.pack("<Q", int((deleted - datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)).total_seconds() * 10_000_000)))
        raw = original.encode("utf-16-le") + b"\x00\x00"
        fh.write(raw.ljust(520, b"\x00"))


def _build_info_v2(path: str, original: str, size: int, deleted: datetime.datetime) -> None:
    """$I metadata file using the modern 0x02 header format."""
    encoded = original.encode("utf-16-le") + b"\x00\x00"
    with open(path, "wb") as fh:
        fh.write(b"\x02\x00\x00\x00\x00\x00\x00\x00")
        fh.write(struct.pack("<Q", size))
        fh.write(struct.pack("<Q", int((deleted - datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)).total_seconds() * 10_000_000)))
        fh.write(struct.pack("<I", len(encoded) // 2))
        fh.write(encoded)


def _container(parts: list[bytes]) -> bytes:
    out = bytearray(b"\x01\x00\x00\x00\x00\x00\x00\x00")
    for part in parts:
        out.append(0x02)
        out += struct.pack("<I", len(part))
        out += part
    return bytes(out)


@pytest.fixture()
def recycle_dir(tmp_path: Path) -> str:
    sid = "S-1-5-21-123-456-789-1001"
    root = tmp_path / "$Recycle.Bin" / sid
    root.mkdir(parents=True)
    deleted = datetime.datetime(2026, 1, 5, 12, 30, 0, tzinfo=datetime.timezone.utc)
    _build_info(str(root / "$IAAAAAA01.txt"), "C:\\Users\\alice\\Documents\\report.txt", 5, deleted)
    (root / "$RAAAAAA01.txt").write_bytes(b"hello")

    _build_info(str(root / "$IAAAAAA02.jpg"), "D:\\photos\\vacation.jpg", 4_000_000, deleted)
    (root / "$RAAAAAA02.jpg").write_bytes(
        _container([b"\xff\xd8\xff\xe0" + b"a" * 1_999_996, b"b" * 1_999_998 + b"\xff\xd9"])
    )

    (root / "$IUNPAIRED.txt").write_bytes(b"\x00" * 24 + b"\x00" * 520)
    return str(tmp_path / "$Recycle.Bin")


def test_parse_info_file(recycle_dir: str):
    meta = parse_info_file(os.path.join(recycle_dir, "S-1-5-21-123-456-789-1001", "$IAAAAAA01.txt"))
    assert meta.original_path == "C:\\Users\\alice\\Documents\\report.txt"
    assert meta.original_name == "report.txt"
    assert meta.size == 5
    assert meta.deleted_at is not None
    assert meta.deleted_at.year == 2026


def test_parse_info_file_v2(tmp_path: Path):
    sid = tmp_path / "sid"
    sid.mkdir()
    deleted = datetime.datetime(2026, 2, 3, 4, 5, 6, tzinfo=datetime.timezone.utc)
    _build_info_v2(str(sid / "$IAA01.txt"), "D:\\docs\\photo.jpg", 123456, deleted)
    meta = parse_info_file(str(sid / "$IAA01.txt"))
    assert meta.original_path == "D:\\docs\\photo.jpg"
    assert meta.original_name == "photo.jpg"
    assert meta.size == 123456
    assert meta.path_length > 0
    assert meta.deleted_at == deleted


def test_find_recycle_items_mixed_versions(tmp_path: Path):
    root = tmp_path / "$Recycle.Bin" / "S-1-5-21-x"
    root.mkdir(parents=True)
    deleted = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    _build_info(str(root / "$ILEGACY.txt"), "C:\\a\\legacy.txt", 3, deleted)
    (root / "$RLEGACY.txt").write_bytes(b"123")
    _build_info_v2(str(root / "$IMODERN.txt"), "C:\\a\\modern.txt", 3, deleted)
    (root / "$RMODERN.txt").write_bytes(b"456")

    items = find_recycle_items(str(tmp_path / "$Recycle.Bin"))
    names = {i.meta.original_name for i in items}
    assert names == {"legacy.txt", "modern.txt"}


def test_parse_filetime_epoch():
    dt = parse_filetime(struct.pack("<Q", 116444736000000000))
    assert dt is not None and dt.year == 1970


def test_find_recycle_items_pairs(recycle_dir: str):
    items = find_recycle_items(recycle_dir)
    assert len(items) == 2
    by_name = {i.meta.original_name: i for i in items}
    assert "report.txt" in by_name
    assert all(i.data_file.endswith(("$RAAAAAA01.txt", "$RAAAAAA02.jpg")) for i in items)


def test_inline_read(recycle_dir: str):
    items = find_recycle_items(recycle_dir)
    report = next(i for i in items if i.meta.original_name == "report.txt")
    assert read_item(report) == b"hello"


def test_container_expansion(recycle_dir: str):
    items = find_recycle_items(recycle_dir)
    img = next(i for i in items if i.meta.original_name.endswith(".jpg"))
    assert is_container(open(img.data_file, "rb").read(8))
    data = read_item(img)
    assert data.startswith(b"\xff\xd8\xff\xe0")
    assert data.endswith(b"\xff\xd9")
    assert len(data) == 4_000_000


def test_container_size_padding():
    expanded = expand_container(b"\x01\x00\x00\x00\x00\x00\x00\x00" + bytes([0x02]) + struct.pack("<I", 3) + b"abc", 100)
    assert expanded == b"abc" + b"\x00" * 97


def test_reader_roundtrip(recycle_dir: str):
    items = find_recycle_items(recycle_dir)
    img = next(i for i in items if i.meta.original_name.endswith(".jpg"))
    reader = read_item_reader(img)
    assert reader(0, 4) == b"\xff\xd8\xff\xe0"


def test_recycle_scan_recovers(recycle_dir: str, tmp_path: Path):
    from rescuer.engine.scan.recycle import run_recycle_scan

    source = RecoverySource(kind="folder", mount_point=recycle_dir)
    files = run_recycle_scan(source, None)
    assert files
    assert all(f.found_by == "recycle" for f in files)
    assert any(f.name == "report.txt" for f in files)
    assert files[0].reader is not None

    out = tmp_path / "out"
    result = recover_file(files[0], source, str(out), verify_hash=False)
    assert result.ok
    assert Path(result.dest_path).read_bytes() == b"hello"


def test_source_from_scan_folder_kind(db: Database, recycle_dir: str):
    scan_id = db.execute(
        "INSERT INTO scans (device_id, mode, status) VALUES (?, 'recycle', 'completed')",
        (recycle_dir,),
    )
    source = source_from_scan(db, scan_id)
    assert source is not None
    assert source.kind == "folder"
    assert source.mount_point == recycle_dir


def test_source_from_scan_drive_root_is_volume(db: Database):
    scan_id = db.execute(
        "INSERT INTO scans (device_id, mode, status) VALUES ('C:\\', 'recycle', 'completed')"
    )
    source = source_from_scan(db, scan_id)
    assert source is not None
    assert source.kind == "volume"
    assert source.mount_point == "C:\\"


def test_recycle_root_folder_points_at_drive(tmp_path: Path):
    from rescuer.engine.scan.recycle import _recycle_root

    drive = tmp_path / "fakeC"
    drive.mkdir()
    source = RecoverySource(kind="folder", mount_point=str(drive))
    assert _recycle_root(source) == os.path.join(str(drive), "$Recycle.Bin")

    # a folder pointing directly at a $Recycle.Bin is used as-is
    bin_dir = drive / "$Recycle.Bin"
    bin_dir.mkdir()
    source2 = RecoverySource(kind="folder", mount_point=str(bin_dir))
    assert _recycle_root(source2) == str(bin_dir)


def test_quick_scan_raises_device_access_for_volume(monkeypatch, tmp_path: Path):
    from rescuer.engine.fs import tsk as tsk_module
    from rescuer.engine.models import ScanConfig
    from rescuer.engine.scan.quick import run_quick_scan
    from rescuer.exceptions import DeviceAccessError

    vol = tmp_path / "vol"
    vol.mkdir()

    def _denied(source):
        raise DeviceAccessError("Raw access to volumes requires administrator privileges.")

    monkeypatch.setattr(tsk_module.TskSource, "open", _denied)

    source = RecoverySource(kind="volume", mount_point=str(vol))
    with pytest.raises(DeviceAccessError):
        run_quick_scan(source, ScanConfig(mode="quick", source=source))


def test_quick_scan_no_fallback_for_image(monkeypatch, tmp_path: Path):
    from rescuer.engine.fs import tsk as tsk_module
    from rescuer.engine.models import ScanConfig
    from rescuer.engine.scan.quick import run_quick_scan
    from rescuer.exceptions import DeviceAccessError

    def _denied(source):
        raise DeviceAccessError("denied")

    monkeypatch.setattr(tsk_module.TskSource, "open", _denied)

    source = RecoverySource(kind="image", image_path=str(tmp_path / "missing.img"))
    with pytest.raises(DeviceAccessError):
        run_quick_scan(source, ScanConfig(mode="quick", source=source))


def test_recycle_scan_reports_progress(recycle_dir: str):
    from rescuer.engine.scan.recycle import run_recycle_scan

    source = RecoverySource(kind="folder", mount_point=recycle_dir)
    calls: list = []
    files = run_recycle_scan(source, None, progress=lambda d, t, f: calls.append((d, t, f)))
    assert calls, "progress callback never fired"
    assert calls[-1] == (1, 1, len(files))


def test_recycle_scan_honors_cancel_flag(recycle_dir: str):
    from rescuer.engine.scan.recycle import run_recycle_scan

    source = RecoverySource(kind="folder", mount_point=recycle_dir)
    files = run_recycle_scan(source, None, cancel_flag=[True])
    assert files == []


def test_recover_to_original_location(tmp_path: Path):
    from rescuer.engine.recovery.processor import recover_file
    from rescuer.engine.scan.recycle import run_recycle_scan

    original_dir = tmp_path / "Docs"
    original_dir.mkdir()
    original = str(original_dir / "report.txt")

    sid = "S-1-5-21-999"
    root = tmp_path / "bin"
    d = root / "$Recycle.Bin" / sid
    d.mkdir(parents=True)
    deleted = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    _build_info(str(d / "$IFOO1.txt"), original, 5, deleted)
    (d / "$RFOO1.txt").write_bytes(b"hello")

    source = RecoverySource(kind="folder", mount_point=str(root / "$Recycle.Bin"))
    files = run_recycle_scan(source, None)
    found = next(f for f in files if f.name == "report.txt")

    result = recover_file(found, source, str(tmp_path / "out"),
                          verify_hash=False, restore_original=True)
    assert result.ok
    assert Path(result.dest_path) == original_dir / "report.txt"
    assert (original_dir / "report.txt").read_bytes() == b"hello"


def test_recover_recycle_from_db_row(recycle_dir: str, tmp_path: Path):
    from rescuer.engine.recovery.processor import recover_file
    from rescuer.engine.recovery.queue import found_from_row
    from rescuer.engine.scan.recycle import run_recycle_scan

    source = RecoverySource(kind="folder", mount_point=recycle_dir)
    files = run_recycle_scan(source, None)
    report = next(f for f in files if f.name == "report.txt")

    row = {
        "id": 1, "name": report.name, "size": report.size, "is_deleted": 1,
        "found_by": "recycle", "fs_type": "NTFS", "ext": ".txt",
        "path": report.path, "inode": None, "cluster": None, "raw_offset": None,
        "signature_id": None, "created_at": None, "modified_at": None,
        "deleted_at": report.deleted_at, "quality_score": None,
        "confidence": None, "quality_explanation": None, "footer_found": 0,
        "sha256": None,
    }
    found = found_from_row(row, source)
    assert found.reader is None, "simulated DB row must not carry an in-memory reader"

    out = tmp_path / "out"
    result = recover_file(found, source, str(out), verify_hash=False)
    assert result.ok
    assert Path(result.dest_path).read_bytes() == b"hello"
