import hashlib
import io
import logging
import os
import re
import zipfile
from pathlib import Path

from rescuer.engine.models import FoundFile, RecoverySource
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.paths import Paths

log = logging.getLogger("rescuer.engine.preview")

HEAD_LIMIT = 8 * 1024 * 1024
_HEAD_REGION = 2 * 1024 * 1024
_TEXT_EXTS = {"txt", "log", "csv", "ini", "xml", "json", "md", "html", "rtf",
              "sql", "yaml", "yml", "py", "js", "java", "c", "cpp", "h", "php",
              "sh", "bat", "vbs", "conf", "cfg", "ini", "srt", "vtt"}
_OFFICE_ZIP = {"docx", "xlsx", "pptx", "odt", "ods", "odp"}
_IMAGE_SIGS = {"jpeg", "png", "gif", "bmp", "webp", "tiff", "ico", "psd"}
_PDF_SIGS = {"pdf"}
_ARCHIVE_SIGS = {"zip", "7z", "rar", "gz", "tar", "bz2", "xz"}
_VIDEO_SIGS = {"mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "mpg", "mpeg", "3gp"}
_AUDIO_SIGS = {"mp3", "wav", "aac", "ogg", "flac", "wma", "m4a", "wv"}

_registry_cache: SignatureRegistry | None = None


def _default_registry() -> SignatureRegistry | None:
    global _registry_cache
    if _registry_cache is None:
        try:
            _registry_cache = SignatureRegistry.load()
        except Exception as exc:
            log.warning("signature registry unavailable: %s", exc)
    return _registry_cache


def _head_bytes(found: FoundFile, source: RecoverySource | None, n: int = HEAD_LIMIT) -> bytes | None:
    if found.reader is not None:
        try:
            return found.reader(0, n)
        except Exception:
            return None
    path = source.raw_path() if source else None
    if found.raw_offset is not None and path and os.path.exists(path):
        try:
            with open(path, "rb") as fh:
                fh.seek(found.raw_offset)
                return fh.read(n)
        except OSError:
            return None
    return None


def _read_all(found: FoundFile, source: RecoverySource | None, n: int = HEAD_LIMIT) -> bytes | None:
    return _head_bytes(found, source, n)


def _preview_kind(found: FoundFile, registry: SignatureRegistry | None = None) -> str:
    sig = registry.get(found.signature_id) if found.signature_id and registry else None
    if sig is None and found.signature_id:
        sig = (_default_registry() or SignatureRegistry()).get(found.signature_id)
    if sig:
        return sig.preview
    ext = found.ext.lstrip(".").lower()
    if ext in _TEXT_EXTS:
        return "text"
    if ext in ("jpg", "jpeg", "png", "gif", "bmp", "webp"):
        return "image"
    if ext in _PDF_SIGS:
        return "pdf"
    if ext in _OFFICE_ZIP:
        return "office"
    if ext in _VIDEO_SIGS:
        return "video"
    if ext in _AUDIO_SIGS:
        return "audio"
    if ext in _ARCHIVE_SIGS:
        return "archive"
    return "binary"


def _cache_path(found: FoundFile) -> Path:
    key = hashlib.md5(
        f"{found.name}|{found.size}|{found.raw_offset}|{found.inode}".encode("utf-8")
    ).hexdigest()
    return Paths.thumbnails_dir / f"{key}.png"


def generate_thumbnail(
    found: FoundFile,
    source: RecoverySource | None = None,
    registry: SignatureRegistry | None = None,
    size: tuple[int, int] = (360, 360),
    use_cache: bool = True,
) -> str | None:
    """Generate a thumbnail PNG for the file. Returns cache path or None."""
    kind = _preview_kind(found, registry)
    cache = _cache_path(found)
    if use_cache and cache.exists():
        return str(cache)

    data = _read_all(found, source)
    if data is None:
        return None

    try:
        png = None
        if kind == "image":
            png = _thumb_from_image(data, size)
        elif kind == "pdf":
            png = _thumb_from_pdf(data, size)
        elif kind == "office":
            png = None
        elif kind == "archive":
            png = None
        else:
            png = None
        if png is None:
            return None
        Paths.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(png)
        return str(cache)
    except Exception as exc:
        log.warning("thumbnail generation failed for %s: %s", found.name, exc)
        return None


def _thumb_from_image(data: bytes, size: tuple[int, int]) -> bytes | None:
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    img.thumbnail(size, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _thumb_from_pdf(data: bytes, size: tuple[int, int]) -> bytes | None:
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
    from PIL import Image

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img.thumbnail(size, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG")
    doc.close()
    return out.getvalue()


def generate_text_preview(
    found: FoundFile,
    source: RecoverySource | None = None,
    max_chars: int = 100_000,
) -> str | None:
    kind = _preview_kind(found)
    if kind == "text":
        data = _read_all(found, source, max_chars)
        if data is None:
            return None
        return _decode_text(data)
    if kind == "archive":
        data = _read_all(found, source, _HEAD_REGION)
        if data is None:
            return None
        return _archive_listing(data)
    if kind == "office":
        data = _read_all(found, source, _HEAD_REGION)
        if data is None:
            return None
        ext = found.ext.lstrip(".").lower()
        return _office_text(data, ext)
    return None


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _archive_listing(data: bytes) -> str:
    if data[:4] not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "Archive format recognized but listing unavailable."
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()[:200]
        total = len(zf.namelist())
        body = "\n".join(f"  {n}" for n in names)
        more = f"\n  ... and {total - len(names)} more" if total > len(names) else ""
        return f"Archive contents ({total} entries):\n{body}{more}"
    except zipfile.BadZipFile:
        return "Archive appears damaged — cannot list contents."


_TAG_RE = re.compile(r"<[^>]+>")


def _office_text(data: bytes, ext: str) -> str | None:
    if not data.startswith(b"PK"):
        return "Preview not available for this Office binary format."
    xml_part = {"docx": "word/document.xml",
                "xlsx": "xl/sharedStrings.xml",
                "pptx": "ppt/slides/slide1.xml",
                "odt": "content.xml",
                "ods": "content.xml",
                "odp": "content.xml"}.get(ext)
    if xml_part is None:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        if xml_part not in zf.namelist():
            return "No readable text part found in this Office file."
        raw = zf.read(xml_part)
        text = _TAG_RE.sub(" ", raw.decode("utf-8", errors="replace"))
        text = re.sub(r"\s+", " ", text).strip()
        return text[:100_000] if text else "No extractable text."
    except (zipfile.BadZipFile, KeyError):
        return "Office file appears damaged — cannot extract text."


def preview_type(found: FoundFile, registry: SignatureRegistry | None = None) -> str:
    return _preview_kind(found, registry)
