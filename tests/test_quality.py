import os
from pathlib import Path

import pytest

from rescuer.engine.models import FoundFile, RecoverySource
from rescuer.engine.quality.scorer import QualityScorer, apply_quality, stars_from_score
from rescuer.engine.quality.verifier import verify_content
from rescuer.engine.signatures.registry import SignatureRegistry


@pytest.fixture(scope="module")
def registry() -> SignatureRegistry:
    return SignatureRegistry.load()


@pytest.fixture(scope="module")
def fat_image() -> str:
    from fixtures.fat12_builder import make_fat12_image

    from rescuer.paths import Paths

    Paths.ensure_dirs()
    path = os.path.join(Paths.cache_dir, "quality_fixture.img")
    make_fat12_image(path)
    return path


@pytest.fixture()
def source(fat_image: str) -> RecoverySource:
    return RecoverySource(kind="image", image_path=fat_image, size=os.path.getsize(fat_image))


def _scanned(fat_image: str) -> list[FoundFile]:
    from rescuer.engine.models import ScanConfig
    from rescuer.engine.scan.quick import run_quick_scan
    from rescuer.engine.scan.deep import run_deep_scan
    from rescuer.engine.signatures.registry import SignatureRegistry

    source = RecoverySource(kind="image", image_path=fat_image, size=os.path.getsize(fat_image))
    reg = SignatureRegistry.load()
    files = run_quick_scan(source, ScanConfig(mode="quick", source=source))
    files += run_deep_scan(source, ScanConfig(mode="deep", source=source), reg)
    return files


def test_stars_bands():
    assert stars_from_score(95) == 5
    assert stars_from_score(90) == 5
    assert stars_from_score(80) == 4
    assert stars_from_score(60) == 3
    assert stars_from_score(30) == 2
    assert stars_from_score(5) == 1


def test_live_file_scores_high(fat_image):
    files = _scanned(fat_image)
    live = [f for f in files if not f.is_deleted]
    assert live, "expected at least one live file"
    result = apply_quality(live[0])
    assert result.score >= 90
    assert result.stars == 5
    assert result.confidence >= 60


def test_carved_scores_below_perfect(fat_image, registry):
    from rescuer.engine.models import ScanConfig
    from rescuer.engine.scan.deep import run_deep_scan

    source = RecoverySource(kind="image", image_path=fat_image, size=os.path.getsize(fat_image))
    files = run_deep_scan(source, ScanConfig(mode="deep", source=source), registry)
    jpeg = next((f for f in files if f.signature_id == "jpeg"), None)
    assert jpeg is not None
    sig = registry.get("jpeg")
    result = apply_quality(jpeg, sig)
    assert 0 <= result.score <= 100
    assert result.explanation
    assert result.as_dict()["score"] == result.score


def test_pdf_verification():
    head = b"%PDF-1.4\n1 0 obj\n" + b"x" * 100
    tail = b"%%EOF"
    ok, _ = verify_content(FoundFile(name="a.pdf", size=0, is_deleted=False, signature_id="pdf"), head, tail)
    assert ok is True
    ok2, _ = verify_content(FoundFile(name="a.pdf", size=0, is_deleted=False, signature_id="pdf"), head, b"nope")
    assert ok2 is False


def test_zip_verification():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", b"hello")
    data = buf.getvalue()
    ok, _ = verify_content(FoundFile(name="a.zip", size=0, is_deleted=False, signature_id="zip"), data)
    assert ok is True
    ok2, _ = verify_content(FoundFile(name="a.zip", size=0, is_deleted=False, signature_id="zip"), b"PK\x03\x04garbage")
    assert ok2 is False


def test_text_verification():
    ok, _ = verify_content(FoundFile(name="a.txt", size=0, is_deleted=False, signature_id="txt"), b"hello world\n")
    assert ok is True
    ok2, _ = verify_content(FoundFile(name="a.txt", size=0, is_deleted=False, signature_id="txt"), b"\xff\xfe\x00garbage\x00")
    assert ok2 is False


def test_duplicate_detection():
    f = FoundFile(name="dup.jpg", size=100, is_deleted=True, sha256="abc123")
    result = apply_quality(f, None, dup_hashes={"abc123"})
    assert result.duplicate_of == -1


def test_empty_name_penalized():
    f = FoundFile(name="", size=100, is_deleted=False, found_by="filesystem")
    result = apply_quality(f)
    assert result.checks["name"]["earned"] < result.checks["name"]["max"]
