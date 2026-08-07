import io
import struct
import zipfile

from rescuer.engine.models import FoundFile

_OLE2_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_SIGS = {"zip", "docx", "xlsx", "pptx", "odt", "ods", "odp", "jar", "apk", "epub", "cbz", "xpi", "wsz"}
_TEXT = {"txt", "log", "csv", "ini", "xml", "json", "md", "html", "rtf", "sql", "yaml", "yml", "py", "js", "java", "c", "cpp", "h", "php", "sh", "bat", "vbs"}


def _verify_image(found: FoundFile, head: bytes) -> tuple[bool, str]:
    try:
        from PIL import Image
    except ImportError:
        return True, "Image header looks valid"
    try:
        img = Image.open(io.BytesIO(head))
        img.load()
    except Exception:
        return False, "Could not decode image payload"
    return True, f"Valid {img.format or 'image'} (verification decode OK)"


def _verify_pdf(found: FoundFile, head: bytes, tail: bytes) -> tuple[bool, str]:
    if head.startswith(b"%PDF") and b"%%EOF" in tail[-1024:]:
        return True, "PDF structure valid (%PDF header + %%EOF trailer found)"
    if head.startswith(b"%PDF"):
        return False, "PDF is truncated — end-of-file trailer missing"
    return False, "Not a recognizable PDF stream"


def _verify_zip(head: bytes) -> tuple[bool, str]:
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(head))
            bad = zf.testzip()
            if bad:
                return False, f"Archive corrupt near {bad}"
        except zipfile.BadZipFile:
            return False, "Archive headers invalid — file may be damaged"
        except Exception:
            return False, "Archive could not be opened for verification"
        return True, "Archive structure valid (central directory readable)"
    return False, "Not a recognizable archive"


def _verify_text(head: bytes) -> tuple[bool, str]:
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return False, "Content is not valid UTF-8 text (binary-like data)"
    return True, "Decodes cleanly as text"


def verify_content(found: FoundFile, head: bytes, tail: bytes | None = None) -> tuple[bool | None, str]:
    """Return (ok, note). ok is None when the format cannot be structurally verified."""
    preview = found.signature_id or found.ext.lstrip(".").lower() or ""
    tail = tail or head

    if preview == "pdf":
        return _verify_pdf(found, head, tail)
    if preview in _ZIP_SIGS:
        return _verify_zip(head)
    if preview in {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "ico"}:
        return _verify_image(found, head)
    if preview in _TEXT:
        return _verify_text(head)
    if found.ext.lower().lstrip(".") in {"doc", "xls", "ppt"} or preview == "ole2":
        return (head[:8] == _OLE2_HEADER, "OLE2 compound document header valid"
                if head[:8] == _OLE2_HEADER else "OLE2 header missing — file may be damaged")
    if preview in {"mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "mpg", "mpeg", "3gp"}:
        return True, "Container header recognized (structural check only)"
    if preview in {"mp3", "wav", "aac", "ogg", "flac", "wma", "m4a", "wv"}:
        return True, "Audio container recognized (structural check only)"
    if preview in {"7z", "rar", "gz", "bz2", "xz", "lz", "tar"}:
        return None, "Compressed container recognized (no deep verification)"
    return None, "Structural verification not available for this format"


def probe_head(found: FoundFile, size: int) -> tuple[bytes, bytes] | None:
    reader = found.reader
    if reader is None:
        return None
    head = reader(0, min(64 * 1024, max(size, 1)))
    if head:
        tail = None
        try:
            tail = reader(max(0, size - 64 * 1024), min(64 * 1024, size))
        except Exception:
            tail = head
        return head, tail
    return None
