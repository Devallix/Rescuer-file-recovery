import struct
from io import BytesIO

SECTOR = 512
RESERVED = 1
NUM_FATS = 2
FAT_SECTORS = 9
ROOT_ENTRIES = 224
ROOT_SECTORS = 14
TOTAL_SECTORS = 2880
DATA_START_SECTOR = RESERVED + NUM_FATS * FAT_SECTORS + ROOT_SECTORS
NUM_CLUSTERS = TOTAL_SECTORS - DATA_START_SECTOR

ATTR_READ_ONLY = 0x01
ATTR_DIR = 0x10
ATTR_ARCHIVE = 0x20
END_OF_CHAIN = 0xFFF


def _fat12_encode(entries: list[int]) -> bytes:
    out = bytearray()
    n = len(entries)
    i = 0
    while i < n:
        a = entries[i]
        b = entries[i + 1] if i + 1 < n else 0
        out.append(a & 0xFF)
        out.append(((a >> 8) & 0x0F) | ((b & 0x0F) << 4))
        out.append((b >> 4) & 0xFF)
        i += 2
    return bytes(out)


def _dtime(timestamp: tuple[int, int, int, int, int, int] | None = None) -> tuple[int, int]:
    year, month, day, hour, minute, second = timestamp or (2024, 1, 1, 12, 0, 0)
    time_word = (hour << 11) | (minute << 5) | (second // 2)
    date_word = ((year - 1980) << 9) | (month << 5) | day
    return time_word, date_word


def _entry(name8: bytes, ext3: bytes, attr: int, cluster: int, size: int, deleted: bool = False) -> bytes:
    b = bytearray(32)
    raw = name8[:8].ljust(8, b" ") + ext3[:3].ljust(3, b" ")
    if deleted:
        raw = b"\xe5" + raw[1:]
    b[0:11] = raw
    b[11] = attr
    time_word, date_word = _dtime()
    struct.pack_into("<H", b, 22, time_word)
    struct.pack_into("<H", b, 24, date_word)
    struct.pack_into("<H", b, 26, cluster)
    struct.pack_into("<I", b, 28, size)
    return bytes(b)


class Fat12Builder:
    def __init__(self) -> None:
        self.fat = [0x0FF0, 0x0FFF]
        self.root_entries: list[bytes] = []
        self.data_sectors: list[bytes] = []
        self._next_cluster = 2

    def _allocate(self, content: bytes) -> tuple[int, int]:
        start = self._next_cluster
        clusters_needed = max(1, (len(content) + SECTOR - 1) // SECTOR)
        if self._next_cluster + clusters_needed > NUM_CLUSTERS:
            raise ValueError("fixture image too small")
        chain: list[int] = []
        for i in range(clusters_needed):
            chain.append(self._next_cluster)
            self._next_cluster += 1
        for idx, cluster in enumerate(chain):
            next_value = chain[idx + 1] if idx + 1 < len(chain) else END_OF_CHAIN
            self.fat.append(next_value)
        padded = content.ljust(clusters_needed * SECTOR, b"\x00")
        for off in range(0, len(padded), SECTOR):
            self.data_sectors.append(padded[off:off + SECTOR])
        return start, len(content)

    def add_file(self, name8: bytes, ext3: bytes, content: bytes, deleted: bool = False) -> None:
        cluster, size = self._allocate(content)
        self.root_entries.append(
            _entry(name8, ext3, ATTR_ARCHIVE, cluster, size, deleted=deleted)
        )

    def add_dir(self, name8: bytes, files: list[tuple[bytes, bytes, bytes, bool]]) -> None:
        dir_entries = bytearray()
        dir_entries += _entry(b".", b"", ATTR_DIR, self._next_cluster, 0)
        dir_entries += _entry(b"..", b"", ATTR_DIR, 0, 0)
        for fname8, fext3, content, deleted in files:
            cluster, size = self._allocate(content)
            dir_entries += _entry(fname8, fext3, ATTR_ARCHIVE, cluster, size, deleted=deleted)
        dir_entries += bytes(32)
        cluster, _size = self._allocate(bytes(dir_entries))
        self.root_entries.append(_entry(name8, b"", ATTR_DIR, cluster, 0))

    def build(self) -> bytes:
        image = bytearray(TOTAL_SECTORS * SECTOR)
        image[0:512] = self._boot_sector()
        fat_bytes = _fat12_encode(self.fat)
        fat_padded = fat_bytes.ljust(FAT_SECTORS * SECTOR, b"\x00")
        for i in range(NUM_FATS):
            offset = (RESERVED + i * FAT_SECTORS) * SECTOR
            image[offset:offset + FAT_SECTORS * SECTOR] = fat_padded
        root = bytearray(ROOT_SECTORS * SECTOR)
        for i, e in enumerate(self.root_entries):
            root[i * 32:(i + 1) * 32] = e
        root_offset = (RESERVED + NUM_FATS * FAT_SECTORS) * SECTOR
        image[root_offset:root_offset + ROOT_SECTORS * SECTOR] = root
        for idx, sector in enumerate(self.data_sectors):
            image[(DATA_START_SECTOR + idx) * SECTOR:(DATA_START_SECTOR + idx + 1) * SECTOR] = sector
        return bytes(image)

    def _boot_sector(self) -> bytes:
        b = bytearray(SECTOR)
        b[0:3] = b"\xeb\x3c\x90"
        b[3:11] = b"MKRBAUTO"
        struct.pack_into("<H", b, 11, SECTOR)
        b[13] = 1
        struct.pack_into("<H", b, 14, RESERVED)
        b[16] = NUM_FATS
        struct.pack_into("<H", b, 17, ROOT_ENTRIES)
        struct.pack_into("<H", b, 19, TOTAL_SECTORS)
        b[21] = 0xF0
        struct.pack_into("<H", b, 22, FAT_SECTORS)
        struct.pack_into("<H", b, 24, 18)
        struct.pack_into("<H", b, 26, 2)
        struct.pack_into("<I", b, 28, 0)
        struct.pack_into("<I", b, 32, 0)
        b[36] = 0
        b[38] = 0
        struct.pack_into("<I", b, 39, 0x18)
        struct.pack_into("<I", b, 43, 0)
        b[54] = 0x80
        struct.pack_into("<I", b, 64, 0)
        struct.pack_into("<I", b, 68, 0)
        b[510:512] = b"\x55\xaa"
        return bytes(b)


def make_fat12_image(path: str, extra: list[tuple[bytes, bytes, bytes, bool]] | None = None) -> None:
    builder = Fat12Builder()
    builder.add_file(b"HELLO", b"TXT", b"Hello from Rescuer! This file exists on disk.\n")
    builder.add_file(b"LOST", b"JPG", _tiny_jpeg(), deleted=True)
    builder.add_file(b"SECRET", b"DOC", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"FAKE-OLE2-DOC", deleted=True)
    builder.add_file(b"PIC", b"PNG", _tiny_png())
    builder.add_dir(b"DOCS", [(b"READ", b"TXT", b"Read me please.\n", False),
                              (b"GONE", b"TXT", b"This file was deleted inside a folder.\n", True)])
    if extra:
        for name8, ext3, content, deleted in extra:
            builder.add_file(name8, ext3, content, deleted)
    with open(path, "wb") as fh:
        fh.write(builder.build())


def make_partitioned_image(path: str, partition_start_lba: int = 63) -> None:
    fat = Fat12Builder()
    fat.add_file(b"HELLO", b"TXT", b"Partitioned hello.\n")
    fat.add_file(b"OLD", b"TXT", b"Deleted in partition.\n", deleted=True)
    volume = fat.build()

    mbr = bytearray(512)
    mbr[0:3] = b"\x33\xc0\x8e"
    mbr[446:462] = struct.pack("<B", 0x80) + b"\x01\x01\x00" + bytes([0x06]) + b"\x3f\x00\x00" + struct.pack("<II", partition_start_lba, len(volume) // 512)
    mbr[510:512] = b"\x55\xaa"

    disk = bytearray(partition_start_lba * 512)
    disk[0:512] = mbr
    disk.extend(volume)
    with open(path, "wb") as fh:
        fh.write(bytes(disk))


def _tiny_png() -> bytes:
    buf = BytesIO()
    from PIL import Image
    Image.new("RGB", (2, 2), (120, 200, 40)).save(buf, "PNG")
    return buf.getvalue()


def _tiny_jpeg() -> bytes:
    buf = BytesIO()
    from PIL import Image
    Image.new("RGB", (4, 4), (200, 60, 60)).save(buf, "JPEG", quality=90)
    return buf.getvalue()
