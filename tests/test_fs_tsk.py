import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from rescuer.engine.fs.tsk import (
    TSK_FS_META_FLAG_UNALLOC,
    TSK_FS_NAME_FLAG_UNALLOC,
    TSK_FS_NAME_TYPE_UNDEF,
    TskSource,
)


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
