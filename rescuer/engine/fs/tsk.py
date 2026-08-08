import logging
import os
import struct

import pytsk3

from rescuer.engine.models import FsEntry, RecoverySource
from rescuer.exceptions import DeviceAccessError, DeviceError

log = logging.getLogger("rescuer.engine.fs")

TSK_FS_NAME_FLAG_UNALLOC = 0x02
TSK_FS_NAME_TYPE_UNDEF = 0x00
TSK_FS_NAME_TYPE_DIR = 0x03
TSK_FS_NAME_TYPE_REG = 0x05
TSK_FS_NAME_TYPE_VIRT = 0x0A
TSK_FS_NAME_TYPE_VIRT_DIR = 0x0B
TSK_FS_META_FLAG_UNALLOC = 0x0002

ORPHAN_DIR = "$OrphanFiles"

# Difference between the Windows FILETIME epoch (1601-01-01) and the Unix
# epoch (1970-01-01), in seconds.
_FILETIME_EPOCH = 11644473600.0

# $FILE_NAME attribute type in an NTFS MFT record.
_NTFS_FILE_NAME_ATTR = 0x30


def _filetime_to_epoch(ft: int) -> float | None:
    """Convert a Windows FILETIME (100 ns ticks) to a Unix epoch seconds."""
    if not ft:
        return None
    seconds = ft / 10_000_000.0 - _FILETIME_EPOCH
    return seconds if seconds > 0 else None

_META_FILTER = {"$MBR", "$FAT1", "$FAT2", "$MFT", "$MFTMirr", "$LogFile",
                "$Volume", "$AttrDef", "$Bitmap", "$Boot", "$BadClus",
                "$Secure", "$UpCase", "$Extend", "$Quota", "$ObjId",
                "$Reparse", "$UsnJrnl", "$I30", "$SDS"}


def _vol_path(mount_point: str) -> str:
    mp = mount_point.strip()
    if mp.endswith("\\"):
        mp = mp[:-1]
    if not mp.endswith(":"):
        mp += ":"
    return f"\\\\.\\{mp}"


def _folder_to_tsk_path(folder: str, mount_point: str) -> str:
    """Map a Windows folder under a volume to the TSK-style path used for traversal."""
    mount = (mount_point or "").strip()
    if not mount:
        raise DeviceError("Folder scans require a mounted volume.")
    folder = (folder or "").strip()
    if not folder:
        raise DeviceError("No folder selected.")
    try:
        mount = os.path.normpath(os.path.abspath(mount))
        folder = os.path.normpath(os.path.abspath(folder))
        rel = os.path.relpath(folder, mount)
    except ValueError as exc:
        raise DeviceError(f"Could not resolve {folder} against {mount_point}.") from exc
    if rel == ".." or rel.startswith("..\\") or os.path.isabs(rel):
        raise DeviceError(f"The folder {folder} is not on volume {mount_point}.")
    if rel == ".":
        return "/"
    return "/" + rel.replace("\\", "/")


class TskSource:
    def __init__(self, img, fs, start_path: str = "/", scan_orphans: bool = True) -> None:
        self.img = img
        self.fs = fs
        self.fs_type = str(fs.info.ftype)
        self.start_path = start_path
        self.scan_orphans = scan_orphans

    @classmethod
    def open(cls, source: RecoverySource) -> "TskSource":
        try:
            if source.kind == "image":
                img = pytsk3.Img_Info(source.image_path)
            elif source.kind == "volume":
                img = pytsk3.Img_Info(_vol_path(source.mount_point))
            else:
                raise DeviceError(f"Unsupported source kind: {source.kind}")
            fs = pytsk3.FS_Info(img)
            start_path, scan_orphans = cls._resolve_scan_root(source)
            if start_path != "/":
                try:
                    fs.open_dir(start_path)
                except (IOError, OSError, RuntimeError) as exc:
                    raise DeviceError(
                        f"Folder {source.path} was not found on {source.display_name}: {exc}"
                    ) from exc
            return cls(img, fs, start_path=start_path, scan_orphans=scan_orphans)
        except (IOError, OSError, RuntimeError) as exc:
            raise DeviceAccessError(
                f"Could not open {source.display_name}: {exc}. "
                "Raw access to volumes requires administrator privileges."
            ) from exc

    @staticmethod
    def _resolve_scan_root(source: RecoverySource) -> tuple[str, bool]:
        """Return (tsk_start_path, scan_orphans) honouring a folder-scoped scan."""
        folder = (source.path or "").strip()
        if not folder:
            return "/", True
        if source.kind == "image":
            tsk_path = "/" + folder.strip("/").replace("\\", "/")
            tsk_path = tsk_path.rstrip("/") or "/"
            if tsk_path == "/":
                return "/", True
            return tsk_path, False
        tsk_path = _folder_to_tsk_path(folder, source.mount_point)
        if tsk_path == "/":
            return "/", True
        return tsk_path, False

    def walk(self) -> list[FsEntry]:
        return list(self.iter_entries())

    def iter_entries(self, progress=None, cancel_flag: list[bool] | None = None):
        seen: set[int] = set()
        # Directory inodes reachable from the scan root, mapped to their TSK
        # paths. Used to match deleted $MFT records back to a scanned folder.
        dir_inodes: dict[int, str] = {}
        for entry in self._iter_dir(self.start_path, progress=progress, cancel_flag=cancel_flag):
            if entry.inode >= 0:
                seen.add(entry.inode)
                if entry.is_dir:
                    dir_inodes[entry.inode] = entry.path
            yield entry
        if self.scan_orphans:
            # Orphaned files whose parent directory was itself deleted are not
            # reachable through the tree; TSK exposes them through the virtual
            # $OrphanFiles directory (TSK_FS_ORPHANDIR_INUM == last_inum).
            for entry in self.iter_orphans(progress=progress, cancel_flag=cancel_flag):
                if entry.inode >= 0 and entry.inode in seen:
                    continue
                if entry.inode >= 0:
                    seen.add(entry.inode)
                yield entry
        if self._is_ntfs():
            # On NTFS the directory index usually discards deleted entries
            # (the index root/INDX slack is compacted away on busy volumes
            # like the system drive), so a folder walk alone reports nothing.
            # Scan the $MFT for unallocated records whose parent directory is
            # inside the scanned subtree to recover them.
            root_inode = self._root_dir_inode()
            if root_inode is not None and root_inode not in dir_inodes:
                dir_inodes[root_inode] = self.start_path
            yield from self._iter_mft_deleted(dir_inodes, seen, progress=progress, cancel_flag=cancel_flag)

    def _is_ntfs(self) -> bool:
        try:
            # TSK_FS_TYPE_NTFS == 1
            return bool(int(self.fs_type) & 1)
        except (TypeError, ValueError):
            return False

    def _root_dir_inode(self) -> int | None:
        """Inode of the directory being scanned (its ``.`` entry)."""
        try:
            directory = self.fs.open_dir(self.start_path)
        except (IOError, OSError, RuntimeError):
            return None
        try:
            for ent in directory:
                name_info = ent.info.name
                if name_info is not None and name_info.name in (b".", "."):
                    return ent.info.meta.addr if ent.info.meta else None
        except (IOError, OSError, RuntimeError):
            return None
        return None

    def _ntfs_mft_record_size(self) -> int:
        """Size of an NTFS MFT record, read from the boot sector."""
        boot = b""
        try:
            boot_file = self.fs.open_meta(inode=7)  # $Boot
            boot = boot_file.read_random(0, 512)
        except (IOError, OSError, RuntimeError, TypeError):
            pass
        if len(boot) < 0x41 or boot[3:8] != b"NTFS ":
            try:
                boot = self.img.read(0, 512)
            except (IOError, OSError, RuntimeError, TypeError):
                return 0
        if len(boot) < 0x41 or boot[3:8] != b"NTFS ":
            return 0
        bpt = int.from_bytes(boot[0x40:0x41], "little", signed=True)
        if bpt == 0:
            return 1024
        size = 1 << bpt if bpt > 0 else 1 << -bpt
        return size if 256 <= size <= 65536 else 0

    def _iter_mft_deleted(
        self,
        dir_inodes: dict[int, str],
        seen: set[int],
        progress=None,
        cancel_flag: list[bool] | None = None,
    ):
        """Recover deleted files on NTFS by scanning unallocated $MFT records.

        ``dir_inodes`` maps directory inodes (inside the scanned subtree) to
        their TSK paths; a deleted record is reported when its $FILE_NAME
        parent directory is in that subtree. Deleted subdirectories expand the
        set so files deleted together with their parent folder are found too.
        """
        rec_size = self._ntfs_mft_record_size()
        if not rec_size:
            return
        try:
            mft = self.fs.open_meta(inode=0)  # $MFT
            mft_size = mft.info.meta.size
        except (IOError, OSError, RuntimeError, TypeError):
            return
        if mft_size <= 0:
            return

        parent_ok: set[int] = set(dir_inodes)
        dir_paths: dict[int, str] = dict(dir_inodes)

        def parse(rec: bytearray) -> tuple | None:
            if rec[0:4] != b"FILE":
                return None
            if struct.unpack_from("<Q", rec, 0x20)[0] != 0:
                return None  # extension record; the name lives in the base one
            flags = struct.unpack_from("<H", rec, 0x16)[0]
            if flags & 0x0001:
                return None  # record still in use
            usa_off, usa_cnt = struct.unpack_from("<HH", rec, 0x04)
            attr_off = struct.unpack_from("<H", rec, 0x14)[0]
            if usa_cnt > 1 and 0 < usa_off + 2 * usa_cnt <= rec_size:
                fixups = bytes(rec[usa_off + 2: usa_off + 2 * usa_cnt])
                for k in range(1, usa_cnt):
                    s = k * 512 - 2
                    if s >= 2 and s + 2 <= rec_size:
                        rec[s:s + 2] = fixups[2 * k - 2:2 * k]
            pos = attr_off
            while pos + 8 <= rec_size:
                atype, alen = struct.unpack_from("<II", rec, pos)
                if atype == 0xFFFFFFFF:
                    break
                if alen == 0 or pos + alen > rec_size:
                    break
                if atype == _NTFS_FILE_NAME_ATTR:
                    content_off = struct.unpack_from("<H", rec, pos + 0x14)[0]
                    base = pos + content_off
                    name = None
                    parent = 0
                    fsize = 0
                    crtime = mtime = atime = None
                    if base + 0x42 + 2 <= rec_size:
                        parent = struct.unpack_from("<Q", rec, base)[0] & 0xFFFFFFFFFFFF
                        nlen = rec[base + 0x40]
                        raw_name = bytes(rec[base + 0x42: base + 0x42 + 2 * nlen])
                        if nlen and len(raw_name) == 2 * nlen:
                            name = raw_name.decode("utf-16-le", "replace")
                        fsize = struct.unpack_from("<Q", rec, base + 0x30)[0]
                        crtime = _filetime_to_epoch(struct.unpack_from("<Q", rec, base + 0x08)[0])
                        mtime = _filetime_to_epoch(struct.unpack_from("<Q", rec, base + 0x10)[0])
                        atime = _filetime_to_epoch(struct.unpack_from("<Q", rec, base + 0x20)[0])
                    return (name, parent, bool(flags & 0x0002), fsize, crtime, mtime, atime)
                pos += alen
            return None

        chunk = 16 * 1024 * 1024
        offset = 0
        carry = b""
        while offset < mft_size:
            if cancel_flag and cancel_flag[0]:
                return
            length = min(chunk, mft_size - offset)
            try:
                data = carry + mft.read_random(offset, length)
            except (IOError, OSError, RuntimeError):
                return
            nfull = len(data) // rec_size
            carry = data[nfull * rec_size:]
            for i in range(nfull):
                idx = offset // rec_size + i
                rec = bytearray(data[i * rec_size:(i + 1) * rec_size])
                parsed = parse(rec)
                if parsed is None:
                    continue
                name, parent, is_dir, fsize, crtime, mtime, atime = parsed
                if parent not in parent_ok:
                    continue
                if is_dir:
                    if idx not in dir_paths:
                        base = dir_paths.get(parent, self.start_path)
                        dir_paths[idx] = f"{base}/{name}"
                        parent_ok.add(idx)
                    continue
                if idx in seen:
                    continue
                seen.add(idx)
                base = dir_paths.get(parent, self.start_path)
                full_path = f"{base}/{name}"
                entry = FsEntry(
                    name=name,
                    path=full_path,
                    size=fsize,
                    is_dir=False,
                    is_deleted=True,
                    fs_type=self.fs_type,
                    inode=idx,
                    name_flags=TSK_FS_NAME_FLAG_UNALLOC,
                    created=crtime,
                    modified=mtime,
                    accessed=atime,
                    cluster=idx,
                )
                self._make_reader(entry, idx)
                if progress is not None:
                    progress()
                yield entry
            offset += chunk
            if progress is not None:
                progress()

    def iter_orphans(self, progress=None, cancel_flag: list[bool] | None = None):
        if not self._supports_orphans(self.fs_type):
            return
        try:
            directory = self.fs.open_dir(inode=self.fs.info.last_inum)
        except (IOError, OSError, RuntimeError, TypeError):
            try:
                directory = self.fs.open_dir(None, self.fs.info.last_inum)
            except (IOError, OSError, RuntimeError, TypeError):
                return
        for file_obj in directory:
            if cancel_flag and cancel_flag[0]:
                return
            entry = self._convert(file_obj, "OrphanFiles")
            if entry is None:
                continue
            if progress is not None:
                progress()
            yield entry

    @staticmethod
    def _supports_orphans(fs_type: str) -> bool:
        """True when the filesystem exposes an orphan/inode scan.

        TSK only reports unlinked-but-open files through the virtual
        $OrphanFiles directory on NTFS and the EXT family; FAT, exFAT and
        ISO images must go through raw carving instead.
        """
        try:
            ftype = int(fs_type)
        except (TypeError, ValueError):
            return False
        # TSK_FS_TYPE_NTFS=1, TSK_FS_TYPE_EXT2=128, EXT3=256, EXT4=8192
        return bool(ftype & (1 | 128 | 256 | 8192))

    def _iter_dir(self, path: str, progress=None, cancel_flag: list[bool] | None = None):
        if cancel_flag and cancel_flag[0]:
            return
        try:
            directory = self.fs.open_dir(path)
        except (IOError, OSError, RuntimeError):
            return
        for file_obj in directory:
            if cancel_flag and cancel_flag[0]:
                return
            entry = self._convert(file_obj, path)
            if entry is None:
                continue
            if progress is not None:
                progress()
            yield entry
            if entry.is_dir and not entry.is_deleted:
                yield from self._iter_dir(entry.path, progress=progress, cancel_flag=cancel_flag)

    def _convert(self, file_obj, parent: str) -> FsEntry | None:
        info = file_obj.info
        if info is None:
            return None
        name_info = info.name
        if name_info is None or name_info.name is None:
            return None
        name = name_info.name.decode("utf-8", "replace")
        if name in (".", ".."):
            return None
        meta = info.meta

        if name_info.type in (TSK_FS_NAME_TYPE_VIRT, TSK_FS_NAME_TYPE_VIRT_DIR):
            if name in _META_FILTER:
                return None
            if name in (ORPHAN_DIR, "OrphanFiles", ORPHAN_DIR + "/"):
                pass
            elif name.startswith("$"):
                return None

        if name.startswith("$") and name in _META_FILTER:
            return None

        is_orphan = name_info.type == TSK_FS_NAME_TYPE_UNDEF

        if not is_orphan:
            is_dir = name_info.type == TSK_FS_NAME_TYPE_DIR
            if not is_dir and name_info.type != TSK_FS_NAME_TYPE_REG:
                return None

        addr_hint = name_info.meta_addr if name_info.meta_addr else None

        # TSK stores the name sequence of unallocated/orphan entries one
        # less than the live MFT sequence, so tsk_fs_dir_get unloads the
        # meta as a stale reference. Reload it directly from the inode so
        # we keep the real size, timestamps and data address.
        if meta is None and addr_hint is not None:
            try:
                meta_file = self.fs.open_meta(addr_hint)
                if meta_file is not None and meta_file.info is not None:
                    meta = meta_file.info.meta
            except (IOError, OSError, RuntimeError):
                meta = None

        if is_orphan:
            is_dir = bool(meta and meta.type == pytsk3.TSK_FS_META_TYPE_DIR)

        full_path = f"/{name}" if parent == "/" else f"{parent}/{name}"
        size = meta.size if meta else 0
        is_deleted = True if is_orphan else bool(name_info.flags & TSK_FS_NAME_FLAG_UNALLOC)
        addr = meta.addr if meta else (addr_hint if addr_hint is not None else -1)

        entry = FsEntry(
            name=name,
            path=full_path,
            size=size,
            is_dir=is_dir,
            is_deleted=is_deleted,
            fs_type=self.fs_type,
            inode=addr,
            name_flags=name_info.flags,
            created=meta.crtime if meta else None,
            modified=meta.mtime if meta else None,
            accessed=meta.atime if meta else None,
            cluster=addr if meta else None,
        )
        if not is_dir:
            self._make_reader(entry, addr)
        return entry

    def _make_reader(self, entry: FsEntry, addr: int) -> None:
        fs = self.fs

        def read(offset: int, count: int) -> bytes:
            try:
                f = fs.open_meta(addr)
                return f.read_random(offset, count)
            except (IOError, RuntimeError, OSError) as exc:
                log.debug("read failed inode %s: %s", addr, exc)
                return b""

        entry.reader = read


class TskReaderSession:
    def __init__(self, source: RecoverySource) -> None:
        self.tsk = TskSource.open(source)

    def read(self, inode: int, offset: int, count: int) -> bytes:
        try:
            f = self.tsk.fs.open_meta(inode)
            return f.read_random(offset, count)
        except (IOError, RuntimeError, OSError) as exc:
            log.debug("read failed inode %s: %s", inode, exc)
            return b""
