import datetime
import os

from rescuer.engine.models import FoundFile, RecoverySource, ScanConfig
from rescuer.engine.recycle.parser import find_recycle_items, read_item_reader


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat(sep=" ", timespec="seconds")


def _recycle_root(source: RecoverySource) -> str:
    """Locate the $Recycle.Bin folder for a volume, image, or folder source."""
    root = source.raw_path()
    if source.kind == "folder" and os.path.isdir(root):
        stripped = root.rstrip("\\/")
        if stripped and os.path.basename(stripped).lower() == "$recycle.bin":
            return root
        return stripped + "\\$Recycle.Bin"
    base = root
    if base and not base.endswith(("\\", "/")):
        base += "\\"
    return os.path.join(os.path.dirname(base) or base, "$Recycle.Bin")


def run_recycle_scan(
    source: RecoverySource,
    config: ScanConfig,
    registry=None,
    progress=None,
    cancel_flag=None,
) -> list[FoundFile]:
    """Enumerate deleted files still present in the Windows Recycle Bin."""
    root = _recycle_root(source)
    items = find_recycle_items(root, progress=progress, cancel_flag=cancel_flag)

    files: list[FoundFile] = []
    for item in items:
        files.append(
            FoundFile(
                name=item.meta.original_name or "Recycled file",
                size=item.meta.size,
                is_deleted=True,
                found_by="recycle",
                fs_type="NTFS",
                ext=os.path.splitext(item.meta.original_name or "")[1],
                path=item.meta.original_path,
                deleted_at=_iso(item.meta.deleted_at),
                reader=read_item_reader(item),
            )
        )
    return files
