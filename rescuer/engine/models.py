from dataclasses import dataclass, field
from typing import Callable

Reader = Callable[[int, int], bytes]


@dataclass
class RecoverySource:
    kind: str = "image"
    mount_point: str = ""
    image_path: str = ""
    device_path: str = ""
    label: str = ""
    fs_type: str = ""
    size: int = 0

    @property
    def display_name(self) -> str:
        if self.kind == "image":
            return self.image_path or self.label or "Image"
        return self.mount_point or self.label or "Volume"

    def raw_path(self) -> str:
        if self.kind == "image":
            return self.image_path
        return self.mount_point


@dataclass
class FsEntry:
    name: str
    path: str
    size: int
    is_dir: bool
    is_deleted: bool
    fs_type: str
    inode: int
    name_flags: int
    created: float | None = None
    modified: float | None = None
    accessed: float | None = None
    reader: Reader | None = None
    cluster: int | None = None


@dataclass
class FoundFile:
    name: str
    size: int
    is_deleted: bool
    found_by: str = "filesystem"
    fs_type: str = ""
    ext: str = ""
    path: str = ""
    inode: int | None = None
    cluster: int | None = None
    raw_offset: int | None = None
    signature_id: str | None = None
    created: str | None = None
    modified: str | None = None
    deleted_at: str | None = None
    score: int | None = None
    confidence: int | None = None
    explanation: str | None = None
    footer_found: bool = False
    reader: Reader | None = None
    file_id: int | None = None
    sha256: str | None = None

    @property
    def display_ext(self) -> str:
        return self.ext.lstrip(".").upper() if self.ext else ""

    @property
    def size_human(self) -> str:
        size = self.size
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"


@dataclass
class ScanConfig:
    mode: str = "quick"
    source: RecoverySource | None = None
    filters: dict = field(default_factory=dict)
    workers: int = 0


@dataclass
class ScanProgress:
    phase: str = ""
    scanned: int = 0
    total: int = 0
    found: int = 0

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(1.0, self.scanned / self.total)
