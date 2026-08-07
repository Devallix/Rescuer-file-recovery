import multiprocessing
import os
import logging

from rescuer.engine.models import FoundFile, RecoverySource, ScanConfig
from rescuer.engine.signatures.matcher import carve_from_file, find_matches
from rescuer.engine.signatures.registry import Signature, SignatureRegistry

log = logging.getLogger("rescuer.engine.scan")

CHUNK_SIZE = 4 * 1024 * 1024
IN_PROCESS_LIMIT = 32 * 1024 * 1024


def _scan_range(image_path: str, start: int, end: int, registry: SignatureRegistry) -> list[dict]:
    sigs = [s for s in registry.signatures if s.carve]
    max_header = max((max(len(h.data) + h.offset for h in s.headers) for s in sigs), default=0)
    overlap = max(max_header, 32)
    results: list[dict] = []
    with open(image_path, "rb") as fh:
        fh.seek(start)
        pos = start
        tail = b""
        while pos < end:
            want = min(CHUNK_SIZE, end - pos)
            data = fh.read(want)
            if not data:
                break
            chunk = tail + data
            base = pos - len(tail)
            matches = find_matches(chunk, base, sigs)
            for m in matches:
                carved = carve_from_file(image_path, m)
                if carved.size < m.signature.min_size:
                    continue
                results.append({
                    "offset": carved.offset,
                    "signature_id": m.signature.id,
                    "size": carved.size,
                    "footer_found": carved.footer_found,
                })
            tail = chunk[-overlap:] if len(chunk) > overlap else chunk
            pos += len(data)
    return results


def _split_ranges(size: int, parts: int) -> list[tuple[int, int]]:
    ranges = []
    step = max(1, size // parts)
    start = 0
    while start < size:
        ranges.append((start, min(start + step, size)))
        start += step
    return ranges


def run_deep_scan(
    source: RecoverySource,
    config: ScanConfig,
    registry: SignatureRegistry,
    progress=None,
    cancel_flag: list[bool] | None = None,
) -> list[FoundFile]:
    image_path = source.raw_path()
    size = source.size or os.path.getsize(image_path)
    filters = config.filters or {}
    use_processes = config.workers > 0 and size > IN_PROCESS_LIMIT

    all_results: list[dict] = []
    if use_processes:
        workers = min(config.workers, 8)
        ranges = _split_ranges(size, workers * 4)
        scanned = [0]

        def _done(chunk_results, rng):
            all_results.extend(chunk_results)
            scanned[0] += rng[1] - rng[0]
            if progress:
                progress(scanned[0], size, len(all_results))
            if cancel_flag and cancel_flag[0]:
                return False
            return True

        try:
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(workers) as pool:
                futures = []
                for rng in ranges:
                    futures.append(pool.apply_async(_scan_range, (image_path, rng[0], rng[1], registry)))
                for fut, rng in zip(futures, ranges):
                    chunk_results = fut.get()
                    if not _done(chunk_results, rng):
                        break
        except Exception as exc:
            log.warning("multiprocess scan failed (%s); falling back to in-process", exc)
            all_results = []
            _scan_in_process(image_path, size, registry, filters, progress, cancel_flag, all_results)
            return _to_found_files(all_results, registry)
    else:
        _scan_in_process(image_path, size, registry, filters, progress, cancel_flag, all_results)

    return _to_found_files(all_results, registry)


def _scan_in_process(image_path, size, registry, filters, progress, cancel_flag, sink) -> None:
    scanned = [0]
    sigs = [s for s in registry.signatures if s.carve]
    max_header = max((max(len(h.data) + h.offset for h in s.headers) for s in sigs), default=0)
    overlap = max(max_header, 32)
    with open(image_path, "rb") as fh:
        pos = 0
        tail = b""
        while pos < size:
            if cancel_flag and cancel_flag[0]:
                break
            want = min(CHUNK_SIZE, size - pos)
            data = fh.read(want)
            if not data:
                break
            chunk = tail + data
            base = pos - len(tail)
            for m in find_matches(chunk, base, sigs):
                carved = carve_from_file(image_path, m)
                if carved.size < m.signature.min_size:
                    continue
                sink.append({
                    "offset": carved.offset,
                    "signature_id": m.signature.id,
                    "size": carved.size,
                    "footer_found": carved.footer_found,
                })
            tail = chunk[-overlap:] if len(chunk) > overlap else chunk
            pos += len(data)
            scanned[0] += len(data)
            if progress:
                progress(scanned[0], size, len(sink))


def _to_found_files(results: list[dict], registry: SignatureRegistry | None = None) -> list[FoundFile]:
    files: list[FoundFile] = []
    for r in results:
        sig = None
        if registry is not None:
            sig = registry.get(r["signature_id"])
        ext = f".{sig.extensions[0]}" if sig and sig.extensions else ""
        name = f"Recovered{ext}" if ext else f"Recovered.{r['signature_id']}"
        files.append(
            FoundFile(
                name=name,
                size=r["size"],
                is_deleted=True,
                found_by="signature",
                ext=ext,
                raw_offset=r["offset"],
                signature_id=r["signature_id"],
                footer_found=r["footer_found"],
            )
        )
    return files
