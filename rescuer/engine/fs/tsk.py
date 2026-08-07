import logging
import os

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
        for entry in self._iter_dir(self.start_path, progress=progress, cancel_flag=cancel_flag):
            if entry.inode >= 0:
                seen.add(entry.inode)
            yield entry
        if not self.scan_orphans:
            return
        # Orphaned files whose parent directory was itself deleted are not
        # reachable through the tree; TSK exposes them through the virtual
        # $OrphanFiles directory (TSK_FS_ORPHANDIR_INUM == last_inum).
        for entry in self.iter_orphans(progress=progress, cancel_flag=cancel_flag):
            if entry.inode >= 0 and entry.inode in seen:
                continue
            if entry.inode >= 0:
                seen.add(entry.inode)
            yield entry

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
