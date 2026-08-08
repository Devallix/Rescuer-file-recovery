import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from rescuer.engine.fs.tsk import (
    TSK_FS_META_FLAG_UNALLOC,
    TSK_FS_NAME_FLAG_UNALLOC,
    TSK_FS_NAME_TYPE_UNDEF,
    TskSource,
    _folder_to_tsk_path,
)
from rescuer.engine.models import RecoverySource
from rescuer.exceptions import DeviceError


class _FakeName:
    def __init__(self, name, type_, meta_addr, flags=0):
        self.name = name
        self.type = type_
        self.meta_addr = meta_addr
        self.flags = flags


class _FakeMeta:
    def __init__(self, addr, size, type_, flags):
        self.addr = addr
        self.size = size
        self.type = type_
        self.flags = flags
        self.crtime = 1000.0
        self.mtime = 2000.0
        self.atime = 3000.0


class _FakeInfo:
    def __init__(self, name, meta=None):
        self.name = name
        self.meta = meta


class _FakeFile:
    def __init__(self, name, meta=None):
        self.info = _FakeInfo(name, meta)


class _FakeFS:
    def __init__(self, meta_by_addr):
        self._meta = meta_by_addr

    def open_meta(self, addr):
        if addr not in self._meta:
            raise RuntimeError(f"no meta {addr}")
        return _FakeFile(None, self._meta[addr])


def _source(fs, fs_type="7"):
    src = TskSource.__new__(TskSource)
    src.fs = fs
    src.fs_type = fs_type
    return src


REG_META = 1  # TSK_FS_META_TYPE_REG
DIR_META = 2  # TSK_FS_META_TYPE_DIR


def test_convert_orphan_with_stale_meta_is_kept():
    meta = _FakeMeta(42, 2048, REG_META, TSK_FS_META_FLAG_UNALLOC)
    name = _FakeName(b"report.docx", TSK_FS_NAME_TYPE_UNDEF, 42, TSK_FS_NAME_FLAG_UNALLOC)
    fs = _FakeFS({42: meta})
    entry = _source(fs)._convert(_FakeFile(name), "/")
    assert entry is not None
    assert entry.name == "report.docx"
    assert entry.is_deleted
    assert not entry.is_dir
    assert entry.size == 2048
    assert entry.inode == 42


def test_convert_orphan_directory_detected_from_meta():
    meta = _FakeMeta(77, 0, DIR_META, TSK_FS_META_FLAG_UNALLOC)
    name = _FakeName(b"old_folder", TSK_FS_NAME_TYPE_UNDEF, 77, TSK_FS_NAME_FLAG_UNALLOC)
    fs = _FakeFS({77: meta})
    entry = _source(fs)._convert(_FakeFile(name), "/")
    assert entry is not None
    assert entry.is_dir
    assert entry.is_deleted


def test_convert_live_regular_file_unchanged():
    meta = _FakeMeta(3, 100, REG_META, 0x0001)  # ALLOC
    name = _FakeName(b"hello.txt", 5, 3, 0x0001)  # REG + ALLOC
    fs = _FakeFS({3: meta})
    entry = _source(fs)._convert(_FakeFile(name, meta), "/")
    assert entry is not None
    assert not entry.is_deleted
    assert entry.size == 100


def test_convert_orphan_without_meta_falls_back_to_hint():
    name = _FakeName(b"lost.bin", TSK_FS_NAME_TYPE_UNDEF, 99, TSK_FS_NAME_FLAG_UNALLOC)
    fs = _FakeFS({99: _FakeMeta(99, 512, REG_META, TSK_FS_META_FLAG_UNALLOC)})
    entry = _source(fs)._convert(_FakeFile(name), "/")
    assert entry is not None
    assert entry.is_deleted
    assert entry.inode == 99
    assert entry.size == 512


def test_supports_orphans_bitmask():
    from rescuer.engine.fs.tsk import TskSource

    assert TskSource._supports_orphans("1") is True       # NTFS
    assert TskSource._supports_orphans("8192") is True    # EXT4
    assert TskSource._supports_orphans("256") is True     # EXT3
    assert TskSource._supports_orphans("128") is True     # EXT2
    assert TskSource._supports_orphans("2") is False      # FAT12
    assert TskSource._supports_orphans("4") is False      # FAT16
    assert TskSource._supports_orphans("8") is False      # FAT32
    assert TskSource._supports_orphans("10") is False     # exFAT
    assert TskSource._supports_orphans("not-an-int") is False


def test_iter_orphans_gated_away_for_fat():
    src = _source(None, fs_type="2")
    assert list(src.iter_orphans()) == []


def test_convert_drops_orphan_files_virtual_dir_entry():
    name = _FakeName(b"$OrphanFiles", 0x0B, 45782, 0x0001)  # VIRT_DIR
    fs = _FakeFS({45782: _FakeMeta(45782, 0, DIR_META, 0x0001)})
    entry = _source(fs)._convert(_FakeFile(name), "/")
    assert entry is None


# ---------------- folder-scoped scans ----------------


class _FakeFsInfo:
    def __init__(self, ftype):
        self.ftype = int(ftype)


class _FakeTreeFS:
    def __init__(self, dirs, ftype="2"):
        self._dirs = dirs
        self.info = _FakeFsInfo(ftype)

    def open_dir(self, path):
        if path in self._dirs:
            return self._dirs[path]
        raise RuntimeError(f"no dir {path}")


def _reg_file(name, addr, deleted=False):
    meta = _FakeMeta(addr, 100, REG_META, TSK_FS_META_FLAG_UNALLOC if deleted else 0x0001)
    name_obj = _FakeName(name.encode(), 5, addr, TSK_FS_NAME_FLAG_UNALLOC if deleted else 0x0001)
    return _FakeFile(name_obj, meta)


def _dir_file(name, addr):
    meta = _FakeMeta(addr, 0, DIR_META, 0x0001)
    name_obj = _FakeName(name.encode(), 0x03, addr, 0x0001)
    return _FakeFile(name_obj, meta)


def test_folder_to_tsk_path():
    assert _folder_to_tsk_path("C:\\Users\\Me", "C:\\") == "/Users/Me"
    assert _folder_to_tsk_path("C:\\Users\\Me\\", "C:\\") == "/Users/Me"
    assert _folder_to_tsk_path("C:\\", "C:\\") == "/"
    assert _folder_to_tsk_path("D:\\Data", "D:\\") == "/Data"


def test_folder_to_tsk_path_off_volume():
    with pytest.raises(DeviceError):
        _folder_to_tsk_path("D:\\Data", "C:\\")


def test_resolve_scan_root_defaults_to_whole_volume():
    src = RecoverySource(kind="volume", mount_point="C:\\")
    assert TskSource._resolve_scan_root(src) == ("/", True)


def test_resolve_scan_root_folder_scoped():
    src = RecoverySource(kind="volume", mount_point="C:\\", path="C:\\Users\\Me\\Docs")
    assert TskSource._resolve_scan_root(src) == ("/Users/Me/Docs", False)


def test_resolve_scan_root_volume_root_folder():
    src = RecoverySource(kind="volume", mount_point="C:\\", path="C:\\")
    assert TskSource._resolve_scan_root(src) == ("/", True)


def test_resolve_scan_root_image_uses_tsk_path():
    src = RecoverySource(kind="image", image_path="x.img", path="/Docs")
    assert TskSource._resolve_scan_root(src) == ("/Docs", False)


def test_walk_full_volume_reaches_subfolders():
    root = [_dir_file("sub", 10), _reg_file("root.txt", 1, deleted=True)]
    sub = [_reg_file("gone.txt", 2, deleted=True), _reg_file("live.txt", 3)]
    fs = _FakeTreeFS({"/": root, "/sub": sub})
    src = TskSource(None, fs)
    assert {e.name for e in src.iter_entries()} == {"sub", "root.txt", "gone.txt", "live.txt"}


def test_walk_folder_only_scans_subtree():
    root = [_dir_file("sub", 10), _reg_file("root.txt", 1, deleted=True)]
    sub = [_reg_file("gone.txt", 2, deleted=True), _reg_file("live.txt", 3)]
    fs = _FakeTreeFS({"/": root, "/sub": sub})
    src = TskSource(None, fs, start_path="/sub", scan_orphans=False)
    assert {e.name for e in src.iter_entries()} == {"gone.txt", "live.txt"}


# ---------------- NTFS $MFT deleted-record scan ----------------

import struct


def _build_mft_record(name, parent, fsize=100, is_dir=False):
    """Build a valid 1024-byte NTFS MFT record with one $FILE_NAME attr."""
    rec = bytearray(1024)
    rec[0:4] = b"FILE"
    usa_off, usa_cnt = 0x30, 3
    struct.pack_into("<HH", rec, 0x04, usa_off, usa_cnt)
    struct.pack_into("<H", rec, 0x10, 1)  # sequence
    struct.pack_into("<H", rec, 0x12, 1)  # hard links
    struct.pack_into("<H", rec, 0x14, 0x38)  # first attribute
    struct.pack_into("<H", rec, 0x16, 0x02 if is_dir else 0x00)  # flags (not in use)
    struct.pack_into("<H", rec, 0x18, 0x0200)  # used bytes
    name_bytes = name.encode("utf-16-le")
    content_len = 0x42 + len(name_bytes)
    attr_len = 0x18 + content_len
    attr = 0x38
    struct.pack_into("<I", rec, attr + 0x00, 0x30)  # $FILE_NAME
    struct.pack_into("<I", rec, attr + 0x04, attr_len)
    struct.pack_into("<I", rec, attr + 0x10, content_len)
    struct.pack_into("<H", rec, attr + 0x14, 0x18)
    base = attr + 0x18
    struct.pack_into("<Q", rec, base + 0x00, parent)  # parent file reference
    struct.pack_into("<Q", rec, base + 0x28, fsize)  # allocated size
    struct.pack_into("<Q", rec, base + 0x30, fsize)  # real size
    rec[base + 0x40] = len(name_bytes) // 2  # name length (chars)
    rec[base + 0x41] = 1  # namespace
    rec[base + 0x42: base + 0x42 + len(name_bytes)] = name_bytes
    struct.pack_into("<I", rec, attr + attr_len, 0xFFFFFFFF)  # end marker
    for k in range(1, usa_cnt):
        tail = rec[k * 512 - 2: k * 512]
        rec[usa_off + 2 * k: usa_off + 2 * k + 2] = tail
    return bytes(rec)


class _FakeMftFile:
    def __init__(self, buf):
        self._buf = buf
        self.info = _FakeSize(len(buf))

    def read_random(self, offset, length):
        return self._buf[offset:offset + length]


class _FakeSize:
    def __init__(self, size):
        self.meta = _FakeMetaSize(size)


class _FakeMetaSize:
    def __init__(self, size):
        self.size = size


class _FakeBoot:
    def read_random(self, offset, length):
        boot = bytearray(512)
        boot[3:8] = b"NTFS "
        return bytes(boot[offset:offset + length])


class _FakeNtfsFS:
    def __init__(self, mft_buf):
        self._mft = mft_buf
        self.info = _FakeFsInfo(1)

    def open_meta(self, addr=None, inode=None, **kwargs):
        a = inode if inode is not None else addr
        if a == 0:
            return _FakeMftFile(self._mft)
        if a == 7:
            return _FakeBoot()
        return _FakeFile(None, None)


def test_mft_deleted_scan_recovers_file_in_folder():
    rec = _build_mft_record("lost.doc", parent=500)
    fs = _FakeNtfsFS(rec)
    src = _source(fs, fs_type="1")
    src.start_path = "/Users/Me/Docs"
    src.img = None
    entries = list(src._iter_mft_deleted({500: "/Users/Me/Docs"}, seen=set()))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "lost.doc"
    assert entry.path == "/Users/Me/Docs/lost.doc"
    assert entry.is_deleted
    assert not entry.is_dir
    assert entry.size == 100
    assert entry.inode == 0


def test_mft_deleted_scan_follows_deleted_subdirectory():
    dir_rec = _build_mft_record("old_folder", parent=500, is_dir=True)
    file_rec = _build_mft_record("child.txt", parent=0, fsize=7)
    buf = dir_rec + file_rec
    fs = _FakeNtfsFS(buf)
    src = _source(fs, fs_type="1")
    src.start_path = "/root"
    src.img = None
    entries = list(src._iter_mft_deleted({500: "/root"}, seen=set()))
    assert len(entries) == 1
    assert entries[0].name == "child.txt"
    assert entries[0].path == "/root/old_folder/child.txt"


def test_mft_deleted_scan_skips_allocated_and_foreign_records():
    live = _build_mft_record("live.txt", parent=500)
    live = bytearray(live)
    live[0x16] = live[0x16] | 0x0001  # mark record as in use
    foreign = _build_mft_record("other.txt", parent=999)
    fs = _FakeNtfsFS(bytes(live) + foreign)
    src = _source(fs, fs_type="1")
    src.start_path = "/root"
    src.img = None
    entries = list(src._iter_mft_deleted({500: "/root"}, seen=set()))
    assert entries == []
