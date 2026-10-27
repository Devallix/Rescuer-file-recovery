from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rescuer.core.database import Database
from rescuer.engine.updates.checker import (
    UpdateError,
    check_for_updates,
    download_update,
    is_newer,
    record_check,
    verify_sha256,
    version_key,
)


class FakeResponse:
    def __init__(self, json_data, status_code=200, headers=None, json_raises=None):
        self._json = json_data
        self._json_raises = json_raises
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP error")

    def json(self):
        if self._json_raises is not None:
            raise self._json_raises
        return self._json

    def iter_content(self, chunk_size=1):
        data = b"x" * 1024
        for _ in range(2):
            yield data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "test.db", Path("rescuer/data/migrations"))


def test_check_for_updates_same_version(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({"version": "0.1.0"})
        result = check_for_updates("0.1.0", "http://example.com/version.json")
        assert result is None


def test_check_for_updates_newer_version(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({
            "version": "0.2.0",
            "url": "http://example.com/download",
            "notes": "Bug fixes",
            "published_at": "2025-01-01",
        })
        result = check_for_updates("0.1.0", "http://example.com/version.json")
        assert result is not None
        assert result.version == "0.2.0"
        assert result.url == "http://example.com/download"
        assert result.notes == "Bug fixes"


def test_check_for_updates_http_error(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({}, status_code=500)
        with pytest.raises(UpdateError):
            check_for_updates("0.1.0", "http://example.com/version.json")


def test_check_for_updates_older_version_is_ignored(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({
            "version": "0.1.1",
            "url": "http://example.com/download",
        })
        assert check_for_updates("0.1.2", "http://example.com/version.json") is None


def test_check_for_updates_accepts_v_prefix_and_numeric_ordering(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({
            "version": "v0.1.10",
            "url": "http://example.com/download",
        })
        result = check_for_updates("0.1.9", "http://example.com/version.json")
    assert result is not None
    assert result.version == "0.1.10"


def test_check_for_updates_missing_version_is_an_error(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({"url": "http://example.com/download"})
        with pytest.raises(UpdateError):
            check_for_updates("0.1.0", "http://example.com/version.json")


def test_check_for_updates_missing_url_is_an_error(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({"version": "0.2.0"})
        with pytest.raises(UpdateError):
            check_for_updates("0.1.0", "http://example.com/version.json")


def test_check_for_updates_non_object_json_is_an_error(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse(["not", "a", "manifest"])
        with pytest.raises(UpdateError):
            check_for_updates("0.1.0", "http://example.com/version.json")


def test_version_key_orders_numerically():
    assert version_key("0.1.10") > version_key("0.1.9")
    assert version_key("v1.0.0") == version_key("1.0")
    assert is_newer("0.2.0", "0.1.9") is True
    assert is_newer("0.1.2", "0.1.2") is False
    assert is_newer("0.1.1", "0.1.2") is False


def test_check_for_updates_invalid_json(db):
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse("not-json", json_raises=ValueError("not json"))
        with pytest.raises(UpdateError):
            check_for_updates("0.1.0", "http://example.com/version.json")


def test_download_update_writes_file(tmp_path):
    dest = str(tmp_path / "update.bin")
    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({}, headers={"Content-Length": "2048"})
        out = download_update("http://example.com/download", dest=dest)
    assert out == dest
    assert open(dest, "rb").read() == b"x" * 2048


def test_download_update_progress_callback(tmp_path):
    progress = []
    dest = str(tmp_path / "update.bin")

    def on_progress(done, total):
        progress.append((done, total))

    with patch("rescuer.engine.updates.checker.requests.get") as mock_get:
        mock_get.return_value = FakeResponse({}, headers={"Content-Length": "2048"})
        download_update("http://example.com/download", dest=dest, progress=on_progress)
    assert len(progress) >= 1
    assert progress[-1] == (2048, 2048)


def test_verify_sha256_matches(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert verify_sha256(str(p), "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824") is True


def test_verify_sha256_mismatch(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert verify_sha256(str(p), "bad") is False


def test_verify_sha256_empty_expected(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert verify_sha256(str(p), "") is True


def test_record_check_logs_event(db):
    record_check(db, "0.1.0", "ok", "detail")
    rows = db.query("SELECT message FROM events WHERE source = 'updates'")
    assert any("update_check" in row["message"] for row in rows)
