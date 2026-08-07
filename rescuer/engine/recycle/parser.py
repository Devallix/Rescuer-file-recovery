import datetime
import os
import struct
from dataclasses import dataclass

from rescuer.exceptions import RecoveryError

_RECORD_MARKER = 0x02
_INLINE_LIMIT = 4096


def _info_version(raw: bytes) -> int | None:
    """Return the $I header version (1 or 2) or None if the header is invalid."""
    if len(raw) < 28:
        return None
    if raw[1:8] != b"\x00" * 7:
        return None
    if raw[0] in (1, 2):
        return raw[0]
    return None


@dataclass
class RecycleMeta:
    original_path: str
    original_name: str
    size: int
    deleted_at: datetime.datetime | None
    path_length: int = 0
    container: bool = False


@dataclass
class RecycleItem:
    meta: RecycleMeta
    data_file: str
    info_file: str

    @property
    def original_dir(self) -> str:
        return os.path.dirname(self.original_path)


def _filenames_match(info_name: str, data_name: str) -> bool:
    i = info_name[2:].split(".", 1)[0] if info_name.startswith("$I") else ""
    d = data_name[2:].split(".", 1)[0] if data_name.startswith("$R") else ""
    return bool(i) and i == d


def _find_path_terminator(buf: bytes) -> int:
    """Locate the WCHAR-aligned null terminator of a UTF-16 path buffer."""
    idx = 0
    while idx + 1 < len(buf):
        if buf[idx] == 0 and buf[idx + 1] == 0:
            return idx
        idx += 2
    return -1


def parse_filetime(raw: bytes) -> datetime.datetime | None:
    """Windows FILETIME (100 ns since 1601-01-01) to aware datetime."""
    try:
        value = struct.unpack("<Q", raw)[0]
    except (struct.error, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(
            microseconds=value / 10
        )
    except (OverflowError, ValueError):
        return None


def parse_info_file(path: str) -> RecycleMeta:
    """Parse a $I metadata file into RecycleMeta.

    Handles both header versions found in the wild:
      * ``0x01`` (legacy) — fixed 520-byte UTF-16 path field at offset 24.
      * ``0x02`` (modern)  — 4-byte path length (in UTF-16 units) at offset 24,
        followed by the UTF-16 path at offset 28.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read(65536)
    except OSError as exc:
        raise RecoveryError(f"Cannot read recycle info file {path}: {exc}") from exc

    version = _info_version(data)
    if version is None:
        raise RecoveryError(f"Not a valid $I file: {path}")

    size = struct.unpack("<Q", data[8:16])[0]
    deleted_at = parse_filetime(data[16:24])

    if version == 2:
        path_length = struct.unpack("<I", data[24:28])[0]
        if 0 < path_length < 65536:
            original_path = (
                data[28:28 + path_length * 2]
                .decode("utf-16-le", errors="replace")
                .rstrip("\x00")
            )
        else:
            original_path = ""
        return RecycleMeta(
            original_path=original_path,
            original_name=os.path.basename(original_path) if original_path else "",
            size=size,
            deleted_at=deleted_at,
            path_length=path_length,
        )

    raw_path = data[24:24 + 520]
    terminator = _find_path_terminator(raw_path)
    path_length = 0
    if terminator != -1:
        original_path = raw_path[:terminator].decode("utf-16-le", errors="replace")
    else:
        # Newer layout: 4-byte path length at offset 520, path follows.
        path_length = struct.unpack("<I", data[520:524])[0]
        if path_length and path_length < 4096:
            end = 524 + path_length
            original_path = data[524:end].decode("utf-16-le", errors="replace").rstrip("\x00")
        else:
            original_path = ""

    return RecycleMeta(
        original_path=original_path,
        original_name=os.path.basename(original_path) if original_path else "",
        size=size,
        deleted_at=deleted_at,
        path_length=path_length,
    )


def is_container(data: bytes) -> bool:
    return len(data) >= 8 and data[1:8] == b"\x00" * 7 and data[0] in (1, 2)


def expand_container(data: bytes, expected_size: int) -> bytes:
    """Expand the record-based container format used for large recycled files."""
    if not is_container(data):
        return data
    out = bytearray()
    pos = 8
    total = len(data)
    while pos < total:
        marker = data[pos]
        if marker != _RECORD_MARKER:
            break
        if pos + 5 > total:
            break
        (length,) = struct.unpack("<I", data[pos + 1:pos + 5])
        pos += 5
        if length == 0 or pos + length > total:
            break
        out.extend(data[pos:pos + length])
        pos += length
    result = bytes(out)
    if expected_size and len(result) < expected_size:
        result += b"\x00" * (expected_size - len(result))
    return result


def read_item(item: RecycleItem, max_bytes: int | None = None) -> bytes:
    """Read the full content of a recycled file, expanding container format."""
    try:
        with open(item.data_file, "rb") as fh:
            data = fh.read() if max_bytes is None else fh.read(max_bytes)
    except OSError as exc:
        raise RecoveryError(f"Cannot read recycle data file {item.data_file}: {exc}") from exc
    return expand_container(data, item.meta.size)


def read_item_reader(item: RecycleItem):
    """Return a Reader(offset, count) -> bytes over the recycled file."""
    full = read_item(item)

    def _read(offset: int, count: int) -> bytes:
        return full[offset:offset + count]

    return _read


def find_recycle_items(
    recycle_root: str,
    progress=None,
    cancel_flag: list[bool] | None = None,
) -> list[RecycleItem]:
    """Scan $Recycle.Bin\\<SID>\\ directories for $I/$R pairs.

    ``progress(processed, total_dirs, found)`` is invoked once per SID folder.
    """
    items: list[RecycleItem] = []
    if not os.path.isdir(recycle_root):
        return items
    sid_dirs = [
        d
        for d in sorted(os.listdir(recycle_root))
        if os.path.isdir(os.path.join(recycle_root, d))
    ]
    total = len(sid_dirs)
    for processed, sid_dir in enumerate(sid_dirs, start=1):
        if cancel_flag is not None and cancel_flag[0]:
            break
        sid_path = os.path.join(recycle_root, sid_dir)
        infos: dict[str, str] = {}
        datas: dict[str, str] = {}
        try:
            names = os.listdir(sid_path)
        except OSError:
            continue
        for name in names:
            full = os.path.join(sid_path, name)
            if os.path.isfile(full) and name.startswith("$I"):
                infos[name] = full
            elif os.path.isfile(full) and name.startswith("$R"):
                datas[name] = full
        for info_name, info_path in infos.items():
            match = next((d for d in datas if _filenames_match(info_name, d)), None)
            if match is None:
                continue
            try:
                meta = parse_info_file(info_path)
            except RecoveryError:
                continue
            meta.container = is_container(open(datas[match], "rb").read(8))
            items.append(RecycleItem(meta=meta, data_file=datas[match], info_file=info_path))
        if progress is not None:
            progress(processed, total, len(items))
    return items


def find_item_by_original_path(recycle_root: str, original_path: str) -> RecycleItem | None:
    """Locate the recycle item whose $I metadata points at ``original_path``."""
    for item in find_recycle_items(recycle_root):
        if item.meta.original_path == original_path:
            return item
    return None


def default_recycle_roots() -> list[str]:
    import string

    roots = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.isdir(drive):
            candidate = os.path.join(drive, "$Recycle.Bin")
            if os.path.isdir(candidate):
                roots.append(candidate)
    return roots
