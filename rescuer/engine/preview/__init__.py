from pathlib import Path

from rescuer.engine.models import FoundFile, RecoverySource
from rescuer.engine.preview.generator import (
    generate_text_preview,
    generate_thumbnail,
    preview_type,
)
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.paths import Paths


def clear_thumbnail_cache() -> int:
    if not Paths.thumbnails_dir.exists():
        return 0
    removed = 0
    for p in Paths.thumbnails_dir.glob("*.png"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def cached_thumbnail_path(found: FoundFile) -> Path | None:
    key = f"{found.name}|{found.size}|{found.raw_offset}|{found.inode}"
    import hashlib

    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    path = Paths.thumbnails_dir / f"{digest}.png"
    return path if path.exists() else None


def build_preview_package(
    found: FoundFile,
    source: RecoverySource | None = None,
    registry: SignatureRegistry | None = None,
    thumb_size: tuple[int, int] = (360, 360),
) -> dict:
    return {
        "kind": preview_type(found, registry),
        "thumbnail": generate_thumbnail(found, source, registry, thumb_size),
        "text": generate_text_preview(found, source),
    }
