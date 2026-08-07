import logging
import os
from pathlib import Path

from rescuer.engine.models import RecoverySource
from rescuer.exceptions import ImagingError

log = logging.getLogger("rescuer.engine.imaging.ewf")

_E01_MAGIC = b"EVF\x07"


def read_e01_header(path: str) -> dict:
    with open(path, "rb") as fh:
        magic = fh.read(4)
    if magic != _E01_MAGIC:
        raise ImagingError(f"Not an E01 file: {path}")
    try:
        import pyewf  # type: ignore
        handle = pyewf.handle()
        handle.open(path)
        return {
            "sectors": handle.get_number_of_sectors(),
            "sector_size": handle.get_sector_size(),
            "compression": handle.get_compression_type(),
            "handle": handle,
        }
    except ImportError as exc:
        raise ImagingError(
            "E01 support requires libewf. Install libewf-python to enable E01 reading."
        ) from exc


def e01_size(path: str) -> int:
    header = read_e01_header(path)
    sectors = header.get("sectors", 0)
    sector_size = header.get("sector_size", 512)
    return sectors * sector_size


def open_e01(path: str) -> RecoverySource:
    header = read_e01_header(path)
    size = header.get("sectors", 0) * header.get("sector_size", 512)
    return RecoverySource(kind="image", image_path=path, size=size)


def read_e01(path: str, offset: int, size: int) -> bytes:
    header = read_e01_header(path)
    handle = header.get("handle")
    if handle is None:
        raise ImagingError("E01 handle not available")
    sector_size = header.get("sector_size", 512)
    start_sector = offset // sector_size
    sector_offset = offset % sector_size
    sectors_needed = (sector_offset + size + sector_size - 1) // sector_size
    try:
        data = handle.read_random(start_sector, sectors_needed)
    except Exception as exc:
        raise ImagingError(f"E01 read failed: {exc}") from exc
    return data[sector_offset:sector_offset + size]
