import datetime
import logging
import os

from rescuer.engine.fs.tsk import TskSource
from rescuer.engine.models import FoundFile, RecoverySource, ScanConfig

log = logging.getLogger("rescuer.engine.scan")


def _iso(ts: float | None) -> str | None:
    if not ts or ts <= 0:
        return None
    try:
        return datetime.datetime.fromtimestamp(ts).isoformat(sep=" ", timespec="seconds")
    except (ValueError, OSError, OverflowError):
        return None


def run_quick_scan(source: RecoverySource, config: ScanConfig) -> list[FoundFile]:
    tsk = TskSource.open(source)
    entries = tsk.walk()
    filters = config.filters or {}
    deleted_only = filters.get("deleted_only", False)
    min_size = filters.get("min_size", 0)
    max_size = filters.get("max_size", 0)

    results: list[FoundFile] = []
    for entry in entries:
        if entry.is_dir:
            continue
        if deleted_only and not entry.is_deleted:
            continue
        if entry.size < min_size:
            continue
        if max_size and entry.size > max_size:
            continue
        ext = os.path.splitext(entry.name)[1]
        results.append(
            FoundFile(
                name=entry.name,
                size=entry.size,
                is_deleted=entry.is_deleted,
                found_by="filesystem",
                fs_type=entry.fs_type,
                ext=ext,
                path=entry.path,
                inode=entry.inode,
                cluster=entry.cluster,
                created=_iso(entry.created),
                modified=_iso(entry.modified),
                deleted_at=_iso(entry.created) if entry.is_deleted else None,
                reader=entry.reader,
            )
        )
    return results
