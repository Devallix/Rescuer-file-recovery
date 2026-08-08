# Rescuer

Your Digital Recovery Companion.

Professional file recovery & data restoration suite for Windows 10/11, built with
Python 3.13+ and PySide6 on top of The Sleuth Kit (`pytsk3`).

## Status

Active development — the full engine and PySide6 UI are implemented, including:

- **Device detection** — volumes, file systems, capacity, health, admin/elevation state
- **Scans** — quick (metadata), deep (signature carving with worker processes), partition analysis, folder scans, and Recycle Bin recovery (with restore-to-original-location)
- **Signature carving** — 150+ file signatures in a data-driven database, with custom-signature support
- **Quality scoring** — 1–5 star Recovery Quality Analyzer with confidence and explanations
- **Previews** — live preview panel for images, PDFs, Office documents, text, and more
- **Recovery** — background queue with pause/stop, SHA-256 verification, duplicate skipping, and saved vault destinations
- **Imaging** — create and read IMG/DD disk images (E01 via `ewf`)
- **Sessions** — named snapshots of completed scans, resumable without rescanning
- **Reports** — HTML, PDF, and CSV exports
- **Search & Smart Assistant** — natural-language filters, type chips, duplicate detection
- **Folder scans** — quick, read-only deleted-file scanning of a single folder
- **Auto-updates** — manifest-based update checks, channels, self-updating installer with rollback
- **System tray** — background scans continue when the window is closed; notifications
- **Plugins** — custom engine hooks via the plugin manager
- **Help menu** — user guide, about, developer, and EULA

See [PLAN.md](PLAN.md) for the roadmap.

## Documentation

User guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — step-by-step instructions
for recovering deleted files, running scans, imaging drives, and generating reports.

## Quick Start

```powershell
pip install -r requirements.txt
python main.py
```

Requires Python 3.13 or newer. Windows 10/11 x64 is the primary target.

## Layout

- `rescuer/ui` — PySide6 presentation layer (pages, widgets, themes)
- `rescuer/engine` — recovery engine (device, scan, carve, signatures, preview, quality)
- `rescuer/core` — app context, config, database, logging, worker pool
- `rescuer/integrations` — native integrations (Win32, FFmpeg, libmagic)
- `rescuer/data` — signature database and SQL migrations
- `tests/` — unit and integration tests

## Tests

```powershell
pip install -e ".[dev]"
pytest
```

## License

Proprietary. All rights reserved.
