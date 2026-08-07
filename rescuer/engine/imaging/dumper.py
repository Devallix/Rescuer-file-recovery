import logging
import os
import time
from dataclasses import dataclass

from rescuer.exceptions import ImagingError

log = logging.getLogger("rescuer.engine.imaging")

CHUNK_SIZE = 4 * 1024 * 1024


@dataclass
class ImageResult:
    path: str
    size: int
    seconds: float
    bytes_read: int

    @property
    def mb_per_sec(self) -> float:
        if self.seconds <= 0:
            return 0.0
        return (self.bytes_read / (1024 * 1024)) / self.seconds


def _normalize_source(path: str) -> str:
    """Convert a drive mount point (C:, C:\\) to a raw volume path (\\\\.\\C:)."""
    p = (path or "").strip().rstrip("\\/")
    if p.startswith(("\\\\.\\", "\\\\?\\")):
        return path
    if len(p) == 2 and p[1] == ":":
        return f"\\\\.\\{p[0]}:"
    return path


def _open_raw(path: str, mode: str = "rb"):
    """Open a raw volume (\\\\.\\C:) or a regular file."""
    path = _normalize_source(path)
    if path.startswith("\\\\.\\"):
        try:
            import win32file
            import win32con

            flags = win32file.FILE_FLAG_SEQUENTIAL_SCAN
            handle = win32file.CreateFileW(
                path,
                win32file.GENERIC_READ,
                win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
                None,
                win32file.OPEN_EXISTING,
                flags,
                0,
            )
            return handle
        except Exception as exc:
            raise ImagingError(f"Cannot open raw volume {path}: {exc}") from exc
    return open(path, mode)


def _read_raw(handle, size: int) -> bytes:
    if hasattr(handle, "read"):
        return handle.read(size)
    import win32file
    import winerror

    result, data = win32file.ReadFile(handle, size)
    if result == winerror.ERROR_HANDLE_EOF:
        return b""
    if result:
        raise ImagingError(f"Raw read failed with code {result}")
    return data


def _seek_raw(handle, offset: int) -> None:
    if hasattr(handle, "seek"):
        handle.seek(offset)
        return
    import win32file

    win32file.SetFilePointer(handle, offset, win32file.FILE_BEGIN)


def _close_raw(handle) -> None:
    if hasattr(handle, "close"):
        handle.close()
    else:
        try:
            import win32file

            win32file.CloseHandle(handle)
        except Exception:
            pass


def image_size(path: str) -> int:
    path = _normalize_source(path)
    if path.startswith("\\\\.\\"):
        drive = path[4:5].upper() + ":\\"
        try:
            import win32api

            total = win32api.GetDiskFreeSpaceEx(drive)[0]
            return int(total)
        except Exception:
            return 0
    if path.lower().endswith(".e01"):
        try:
            from rescuer.engine.imaging.ewf import e01_size

            return e01_size(path)
        except Exception:
            pass
    return os.path.getsize(path)


def create_image(
    source_path: str,
    dest_path: str,
    progress=None,
    cancel_flag: list[bool] | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> ImageResult:
    """Bit-for-bit copy of a raw volume or image file to dest_path."""
    if not source_path:
        raise ImagingError("No source path given")
    start = time.monotonic()
    total = image_size(source_path) or 0
    bytes_read = 0
    handle = None
    try:
        handle = _open_raw(source_path)
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        with open(dest_path, "wb") as out:
            while True:
                if cancel_flag and cancel_flag[0]:
                    raise ImagingError("Imaging cancelled by user")
                data = _read_raw(handle, chunk_size)
                if not data:
                    break
                out.write(data)
                bytes_read += len(data)
                if progress:
                    progress(bytes_read, total)
    finally:
        if handle is not None:
            _close_raw(handle)
    elapsed = time.monotonic() - start
    return ImageResult(dest_path, bytes_read, elapsed, bytes_read)


def verify_image(image_path: str, expected_size: int | None = None, samples: int = 8) -> bool:
    """Basic integrity check: file exists, non-zero, sample sectors readable."""
    if not os.path.exists(image_path):
        return False
    size = os.path.getsize(image_path)
    if size <= 0:
        return False
    if expected_size is not None and size < expected_size:
        return False
    with open(image_path, "rb") as fh:
        fh.seek(0)
        if not fh.read(512):
            return False
        for i in range(samples):
            pos = min((i + 1) * (size // (samples + 1)), size - 1)
            fh.seek(pos)
            fh.read(1)
    return True
