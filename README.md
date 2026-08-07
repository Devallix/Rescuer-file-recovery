# Rescuer

Your Digital Recovery Companion.

Professional file recovery & data restoration suite for Windows 10/11, built with
Python 3.13+ and PySide6 on top of The Sleuth Kit (`pytsk3`).

## Status

Active development — core engine (device, quick/deep/partition scans, signature
carving, quality scoring, previews, recovery queue, imaging, sessions, reports,
search, recycle-bin parsing, plugins) and the full PySide6 UI are implemented.
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
