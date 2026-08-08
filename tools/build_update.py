"""Developer tool: build Rescuer, package the update ZIP, and write manifest.json.

Usage (from the project root):
    python tools/build_update.py              # build + zip + manifest
    python tools/build_update.py --skip-build  # zip only (reuse dist\\Rescuer)
    python tools/build_update.py --notes "Bug fixes"
    python tools/build_update.py --url "https://example.com/rescuer.zip"

Steps:
  1. Optionally re-runs PyInstaller (`python -m PyInstaller --noconfirm --clean Rescuer.spec`).
  2. Packs the whole ``dist\\Rescuer`` folder into ``releases\\Rescuer_<version>.zip``
     (contents at the zip root, so it extracts directly into the install folder).
  3. Writes ``manifest.json`` at the project root (and prints it). Open that file,
     set the ``url`` to your hosted ZIP, then upload the ZIP and serve manifest.json
     (or version.json) at the update endpoint. The URL you edit is reused on the
     next build, so you only edit it once.

In the app, set Settings -> Update endpoint to the URL where the manifest is hosted.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "Rescuer"
RELEASES = ROOT / "releases"
MANIFEST = ROOT / "manifest.json"


def current_version() -> str:
    ns: dict = {}
    exec((ROOT / "rescuer" / "__init__.py").read_text(encoding="utf-8"), ns)
    return str(ns["__version__"])


def run_build() -> None:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "Rescuer.spec"],
        cwd=ROOT,
        check=True,
    )


def make_zip(version: str) -> Path:
    if not DIST.is_dir():
        raise SystemExit(f"Build not found at {DIST}. Run without --skip-build first.")
    RELEASES.mkdir(parents=True, exist_ok=True)
    out = RELEASES / f"Rescuer_{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(DIST.rglob("*")):
            if path.is_dir():
                continue
            zf.write(path, path.relative_to(DIST))
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--notes", default="", help="Release notes shown in the app. Reuses the previous value if omitted.")
    parser.add_argument(
        "--url",
        default="",
        help="Public HTTPS URL of the ZIP. Defaults to the url saved in manifest.json.",
    )
    args = parser.parse_args()

    version = current_version()
    print(f"Version: {version}")

    if not args.skip_build:
        print("Building with PyInstaller…")
        run_build()

    out = make_zip(version)
    digest = sha256(out)
    print(f"ZIP:    {out} ({out.stat().st_size} bytes)")
    print(f"SHA256: {digest}")

    saved_url = ""
    saved_notes = ""
    if MANIFEST.is_file():
        try:
            old = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
            saved_url = str(old.get("url", ""))
            saved_notes = str(old.get("notes", ""))
        except (ValueError, OSError):
            pass
    url = args.url or saved_url or f"https://YOUR-HOST/rescuer-{version}.zip"
    notes = args.notes or saved_notes or f"Release {version}"

    manifest = {
        "version": version,
        "url": url,
        "notes": notes,
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "size_bytes": out.stat().st_size,
        "sha256": digest,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest written to {MANIFEST}")
    print("Only the \"url\" field needs editing (point it at your hosted ZIP).\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
