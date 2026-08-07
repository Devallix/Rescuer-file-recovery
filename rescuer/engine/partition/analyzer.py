import struct
from dataclasses import dataclass


@dataclass
class PartitionInfo:
    index: int
    start_lba: int
    size_lba: int
    type_code: str
    fs_type: str = "unknown"
    active: bool = False

    @property
    def offset(self) -> int:
        return self.start_lba * 512

    @property
    def byte_size(self) -> int:
        return self.size_lba * 512


@dataclass
class PartitionResult:
    table_type: str = "none"
    partitions: list[PartitionInfo] = None

    def __post_init__(self):
        if self.partitions is None:
            self.partitions = []


def _detect_fs(boot: bytes) -> str:
    if len(boot) < 512:
        return "unknown"
    if boot[3:11] == b"NTFS    ":
        return "ntfs"
    if boot[3:11] == b"EXFAT   ":
        return "exfat"
    for label in (b"FAT12", b"FAT16", b"FAT32"):
        if label in boot[54:82] or label in boot[3:11]:
            return label.lower().decode()
    if boot[510:512] == b"\x55\xaa":
        return "fat"
    return "unknown"


def _read(path: str, offset: int, size: int) -> bytes:
    with open(path, "rb") as fh:
        fh.seek(offset)
        return fh.read(size)


def analyze_mbr(path: str, size: int) -> PartitionResult:
    result = PartitionResult(table_type="mbr")
    boot = _read(path, 0, 512)
    if boot[510:512] != b"\x55\xaa":
        return PartitionResult(table_type="none")
    for i in range(4):
        off = 446 + i * 16
        entry = boot[off:off + 16]
        if entry[4] == 0:
            continue
        start_lba, size_lba = struct.unpack("<II", entry[8:16])
        if start_lba == 0 and size_lba == 0:
            continue
        fs = _detect_fs(_read(path, start_lba * 512, 512))
        result.partitions.append(
            PartitionInfo(index=i, start_lba=start_lba, size_lba=size_lba,
                          type_code=f"0x{entry[4]:02X}", fs_type=fs, active=bool(entry[0]))
        )
    return result


def analyze_gpt(path: str, size: int) -> PartitionResult:
    result = PartitionResult(table_type="gpt")
    header = _read(path, 512, 512)
    if header[8:16] != b"EFI PART":
        return PartitionResult(table_type="none")
    if len(header) < 92:
        return result
    first_usable = struct.unpack("<Q", header[40:48])[0]
    last_usable = struct.unpack("<Q", header[48:56])[0]
    num_entries = struct.unpack("<I", header[80:84])[0]
    entry_size = struct.unpack("<I", header[84:88])[0]
    entries_lba = struct.unpack("<Q", header[72:80])[0]
    for i in range(min(num_entries, 128)):
        off = entries_lba * 512 + i * entry_size
        raw = _read(path, off, 128)
        if len(raw) < 128:
            break
        type_guid = raw[0:16]
        if type_guid == b"\x00" * 16:
            continue
        start_lba, end_lba = struct.unpack("<QQ", raw[32:48])
        size_lba = end_lba - start_lba + 1
        fs = _detect_fs(_read(path, start_lba * 512, 512))
        result.partitions.append(
            PartitionInfo(index=i, start_lba=start_lba, size_lba=size_lba,
                          type_code=str(type_guid.hex()), fs_type=fs)
        )
    return result


def analyze(path: str, size: int) -> PartitionResult:
    mbr = analyze_mbr(path, size)
    if mbr.table_type == "mbr" and mbr.partitions:
        return mbr
    if mbr.table_type == "mbr" and size >= 1024 * 512:
        return mbr
    gpt = analyze_gpt(path, size)
    if gpt.table_type == "gpt":
        return gpt
    return mbr


def analyze_boot_area(path: str, size: int) -> str:
    if size < 512:
        return "unknown"
    return _detect_fs(_read(path, 0, 512))
