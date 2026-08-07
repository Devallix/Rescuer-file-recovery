import logging

import pytsk3

from rescuer.engine.models import FsEntry, RecoverySource
from rescuer.exceptions import DeviceAccessError, DeviceError

log = logging.getLogger("rescuer.engine.fs")

TSK_FS_NAME_FLAG_UNALLOC = 0x02
TSK_FS_NAME_TYPE_DIR = 0x03
TSK_FS_NAME_TYPE_REG = 0x05
TSK_FS_NAME_TYPE_VIRT = 0x0A
TSK_FS_NAME_TYPE_VIRT_DIR = 0x0B

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


class TskSource:
    def __init__(self, img, fs) -> None:
        self.img = img
        self.fs = fs
        self.fs_type = str(fs.info.ftype)

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
            return cls(img, fs)
        except (IOError, OSError, RuntimeError) as exc:
            raise DeviceAccessError(
                f"Could not open {source.display_name}: {exc}. "
                "Raw access to volumes requires administrator privileges."
            ) from exc

    def walk(self) -> list[FsEntry]:
        entries: list[FsEntry] = []
        self._walk_dir("/", entries)
        return entries

    def _walk_dir(self, path: str, entries: list[FsEntry]) -> None:
        try:
            directory = self.fs.open_dir(path)
        except (IOError, OSError, RuntimeError):
            return
        for file_obj in directory:
            entry = self._convert(file_obj, path)
            if entry is None:
                continue
            entries.append(entry)
            if entry.is_dir and not entry.is_deleted:
                self._walk_dir(entry.path, entries)

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
            if name in ("$OrphanFiles", "OrphanFiles", "$OrphanFiles/"):
                pass
            elif name.startswith("$"):
                return None

        if name.startswith("$") and name in _META_FILTER:
            return None

        is_dir = name_info.type == TSK_FS_NAME_TYPE_DIR
        if not is_dir and name_info.type != TSK_FS_NAME_TYPE_REG:
            return None

        full_path = name if parent == "/" else f"{parent}/{name}"
        size = meta.size if meta else 0
        is_deleted = bool(name_info.flags & TSK_FS_NAME_FLAG_UNALLOC)
        addr = meta.addr if meta else -1

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
