from dataclasses import dataclass

from rescuer.engine.signatures.registry import Signature


@dataclass
class CandidateMatch:
    offset: int
    signature: Signature
    footer_found: bool = False
    size: int = 0


def find_matches(buffer: bytes, base_offset: int, signatures: list[Signature]) -> list[CandidateMatch]:
    matches: list[CandidateMatch] = []
    for sig in signatures:
        pattern = sig.primary_pattern
        if len(pattern) > len(buffer):
            continue
        start = 0
        while True:
            pos = buffer.find(pattern, start)
            if pos == -1:
                break
            abs_pos = base_offset + pos
            if sig.matches_buffer(buffer, abs_pos):
                matches.append(CandidateMatch(offset=abs_pos, signature=sig))
            start = pos + 1
    matches.sort(key=lambda m: m.offset)
    return matches


def carve_from_file(image_path: str, match: CandidateMatch) -> CandidateMatch:
    sig = match.signature
    max_size = sig.max_size
    if max_size is None:
        max_size = sig.footer.max_gap if sig.footer else 512 * 1024 * 1024
    max_size = max(max_size, sig.min_size)

    footer_data = sig.footer.data if sig.footer else None
    footer_gap = sig.footer.max_gap if sig.footer else 0

    with open(image_path, "rb") as fh:
        fh.seek(match.offset)
        if footer_data:
            remaining = footer_gap
            window = b""
            offset_in_file = match.offset
            while remaining > 0:
                chunk = fh.read(min(remaining, 1_048_576))
                if not chunk:
                    break
                window += chunk
                idx = window.find(footer_data)
                if idx != -1:
                    match.size = idx + len(footer_data)
                    match.footer_found = True
                    return match
                if len(window) > len(footer_data) - 1:
                    window = window[-(len(footer_data) - 1):]
                offset_in_file += len(chunk)
                remaining -= len(chunk)
            match.size = footer_gap - remaining
            match.footer_found = False
            return match
        else:
            data = fh.read(max_size)
            match.size = len(data)
            return match


def _find_footer(image_path: str, start: int, footer: bytes, gap: int) -> int | None:
    with open(image_path, "rb") as fh:
        fh.seek(start)
        remaining = gap
        window = b""
        pos = start
        while remaining > 0:
            chunk = fh.read(min(remaining, 1_048_576))
            if not chunk:
                break
            window += chunk
            idx = window.find(footer)
            if idx != -1:
                return pos + idx
            if len(window) > len(footer) - 1:
                window = window[-(len(footer) - 1):]
            pos += len(chunk)
            remaining -= len(chunk)
    return None


def carve_stream_to_file(image_path: str, match: CandidateMatch, dest: str) -> int:
    sig = match.signature
    max_size = sig.max_size
    if max_size is None:
        max_size = sig.footer.max_gap if sig.footer else 512 * 1024 * 1024
    footer_data = sig.footer.data if sig.footer else None
    footer_gap = sig.footer.max_gap if sig.footer else 0

    footer_abs = None
    if footer_data:
        footer_abs = _find_footer(image_path, match.offset, footer_data, footer_gap)
        if footer_abs is not None:
            footer_abs += len(footer_data)

    written = 0
    with open(image_path, "rb") as src, open(dest, "wb") as out:
        src.seek(match.offset)
        limit = footer_abs - match.offset if footer_abs is not None else max_size
        written = _copy(src, out, limit)
    match.footer_found = footer_abs is not None
    match.size = written
    return written


def _copy(src, out, limit: int) -> int:
    total = 0
    while total < limit:
        chunk = src.read(min(1_048_576, limit - total))
        if not chunk:
            break
        out.write(chunk)
        total += len(chunk)
    return total
