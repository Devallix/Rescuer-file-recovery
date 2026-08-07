import hashlib
import os
import re
import shutil
from dataclasses import dataclass

from rescuer.engine.models import FoundFile, RecoverySource
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.exceptions import RecoveryError

_UNSAFE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


@dataclass
class RecoveryResult:
    file_id: int
    dest_path: str
    status: str
    bytes_written: int = 0
    hash_match: bool | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


def _safe_name(name: str) -> str:
    cleaned = _UNSAFE.sub("_", name).strip().strip(".")
    return cleaned or "recovered"


def _unique_path(dest_dir: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, f"{base} ({counter}){ext}")
        counter += 1
    return candidate


def _sha256_stream(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1_048_576), b""):
            h.update(chunk)
    return h.hexdigest()


def same_volume(source: RecoverySource, dest_dir: str) -> bool:
    if source.kind != "volume":
        return False
    src = os.path.splitdrive(source.mount_point)[0]
    dst = os.path.splitdrive(dest_dir)[0]
    return bool(src) and src.upper() == dst.upper()


def enough_space(dest_dir: str, needed_bytes: int) -> bool:
    try:
        usage = shutil.disk_usage(dest_dir)
        return usage.free >= needed_bytes
    except OSError:
        return True


def _bind_recycle_reader(found: FoundFile, source: RecoverySource) -> None:
    """Re-attach a reader to a recycle-scan result persisted as a DB row."""
    if found.reader is not None or not found.path:
        return
    from rescuer.engine.recycle.parser import find_item_by_original_path, read_item_reader
    from rescuer.engine.scan.recycle import _recycle_root

    try:
        item = find_item_by_original_path(_recycle_root(source), found.path)
    except OSError:
        return
    if item is not None:
        found.reader = read_item_reader(item)
        found.size = item.meta.size


def recover_file(
    found: FoundFile,
    source: RecoverySource,
    dest_dir: str,
    verify_hash: bool = True,
    registry: SignatureRegistry | None = None,
    restore_original: bool = False,
) -> RecoveryResult:
    if found.found_by == "recycle":
        _bind_recycle_reader(found, source)

    if restore_original and found.path:
        original_dir = os.path.dirname(found.path)
        original_name = os.path.basename(found.path)
        if original_dir:
            dest_dir = original_dir
        if original_name:
            found.name = original_name

    if not enough_space(dest_dir, found.size):
        return RecoveryResult(found.file_id, dest_dir, "failed", 0, None, "Not enough free space on destination drive")

    os.makedirs(dest_dir, exist_ok=True)

    ext = found.ext if found.ext else (f".{registry.get(found.signature_id).extensions[0]}"
                                       if registry and found.signature_id and registry.get(found.signature_id).extensions else "")
    filename = _safe_name(found.name if found.name else "recovered")
    if not os.path.splitext(filename)[1] and ext:
        filename += ext

    dest_path = _unique_path(dest_dir, filename)
    bytes_written = 0

    try:
        if found.reader is None and found.inode is not None:
            from rescuer.engine.fs.tsk import TskReaderSession

            session = TskReaderSession(source)
            found.reader = lambda off, count: session.read(found.inode, off, count)

        if found.reader is not None:
            bytes_written = _stream_from_reader(found, dest_path)
        elif found.raw_offset is not None and found.signature_id is not None:
            from rescuer.engine.signatures.matcher import carve_stream_to_file

            sig = registry.find_sig(found.signature_id) if registry else None
            if sig is None:
                raise RecoveryError("Signature registry required for carved recovery")
            bytes_written = carve_stream_to_file(source.raw_path(), found_raw_match(found, sig), dest_path)
            found.size = bytes_written
        else:
            raise RecoveryError("Recovery source unavailable for this file")

        if bytes_written == 0:
            os.remove(dest_path)
            return RecoveryResult(found.file_id, dest_path, "failed", 0, None, "Empty file recovered")

        hash_match = None
        if verify_hash and bytes_written > 0:
            try:
                src_hash = found.sha256 if getattr(found, "sha256", None) else None
                dst_hash = _sha256_stream(dest_path)
                hash_match = dst_hash == src_hash if src_hash else None
            except OSError:
                hash_match = None

        return RecoveryResult(found.file_id, dest_path, "success", bytes_written, hash_match)
    except (OSError, RecoveryError, IOError) as exc:
        try:
            if os.path.exists(dest_path) and bytes_written == 0:
                os.remove(dest_path)
        except OSError:
            pass
        return RecoveryResult(found.file_id, dest_path, "failed", bytes_written, None, str(exc))


def found_raw_match(found: FoundFile, sig) -> "CandidateMatch":
    from rescuer.engine.signatures.matcher import CandidateMatch

    return CandidateMatch(offset=found.raw_offset, signature=sig)


def _stream_from_reader(found: FoundFile, dest_path: str) -> int:
    total = 0
    remaining = found.size
    with open(dest_path, "wb") as out:
        offset = 0
        while remaining > 0:
            chunk = found.reader(offset, min(remaining, 1_048_576))
            if not chunk:
                break
            out.write(chunk)
            total += len(chunk)
            offset += len(chunk)
            remaining -= len(chunk)
    return total
