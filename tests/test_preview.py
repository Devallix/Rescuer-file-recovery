import os
import zipfile
from pathlib import Path

import pytest

from rescuer.engine.models import FoundFile, RecoverySource
from rescuer.engine.preview.generator import generate_text_preview, generate_thumbnail, preview_type
from rescuer.engine.signatures.registry import SignatureRegistry


@pytest.fixture(scope="module")
def registry() -> SignatureRegistry:
    return SignatureRegistry.load()


def _reader_from_bytes(data: bytes):
    def read(offset: int, count: int) -> bytes:
        return data[offset:offset + count]

    return read


def test_preview_type_derived_from_signature(registry):
    f = FoundFile(name="photo", size=10, is_deleted=True, signature_id="jpeg")
    assert preview_type(f, registry) == "image"
    f2 = FoundFile(name="doc", size=10, is_deleted=True, signature_id="pdf")
    assert preview_type(f2, registry) == "pdf"


def test_image_thumbnail_generates_png(tmp_path):
    from fixtures.fat12_builder import _tiny_png

    f = FoundFile(name="pic.png", size=0, is_deleted=False, ext="png", reader=_reader_from_bytes(_tiny_png()))
    path = generate_thumbnail(f, size=(120, 120))
    assert path and Path(path).exists()
    assert Path(path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_thumbnail_bad_image_returns_none():
    f = FoundFile(name="bad.png", size=0, is_deleted=False, ext="png", reader=_reader_from_bytes(b"not an image"))
    assert generate_thumbnail(f) is None


def test_pdf_thumbnail_generates(tmp_path):
    fitz = pytest.importorskip("fitz")
    import io

    from PIL import Image

    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.insert_text((10, 50), "Rescuer preview test")
    buf = io.BytesIO()
    doc.save(buf)
    pdf_bytes = buf.getvalue()
    doc.close()

    f = FoundFile(name="a.pdf", size=0, is_deleted=True, signature_id="pdf", reader=_reader_from_bytes(pdf_bytes))
    path = generate_thumbnail(f)
    assert path and Path(path).exists()
    img = Image.open(path)
    assert img.format == "PNG"


def test_text_preview_decodes():
    f = FoundFile(name="notes.txt", size=0, is_deleted=False, ext="txt", reader=_reader_from_bytes("Hello Réscuer\nline two".encode("utf-8")))
    text = generate_text_preview(f)
    assert "Réscuer" in text


def test_archive_preview_lists_entries(tmp_path):
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("folder/a.txt", "data")
        zf.writestr("b.bin", b"x")
    f = FoundFile(name="bundle.zip", size=0, is_deleted=True, signature_id="zip", reader=_reader_from_bytes(buf.getvalue()))
    text = generate_text_preview(f)
    assert "folder/a.txt" in text and "b.bin" in text


def test_office_docx_text_extraction():
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml",
                    "<?xml version='1.0'?><w:document><w:body><w:p>Hello <w:t>Rescued</w:t> world</w:p></w:body></w:document>")
    f = FoundFile(name="report.docx", size=0, is_deleted=True, ext="docx", reader=_reader_from_bytes(buf.getvalue()))
    text = generate_text_preview(f)
    assert "Hello" in text and "Rescued" in text


def test_carved_file_preview_from_raw_offset(tmp_path):
    from fixtures.fat12_builder import _tiny_png

    img = os.path.join(tmp_path, "vol.img")
    with open(img, "wb") as fh:
        fh.write(b"\x00" * 1000)
        fh.write(_tiny_png())
        fh.write(b"\x00" * 100)
    source = RecoverySource(kind="image", image_path=img, size=os.path.getsize(img))
    f = FoundFile(name="c.png", size=0, is_deleted=True, signature_id="png", raw_offset=1000)
    path = generate_thumbnail(f, source)
    assert path and Path(path).exists()
    assert Path(path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
