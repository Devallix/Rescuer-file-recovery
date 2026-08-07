# Rescuer — Final Development Plan

**Your Digital Recovery Companion.** A premium PySide6 desktop file-recovery suite for Windows (10/11), built on The Sleuth Kit, with enterprise-grade scanning and a polished, glassmorphic UI.

## 1. Decisions & Rationale (verified against the environment)

| Area | Decision | Why |
|---|---|---|
| Python | 3.13+ target; dev on installed 3.14.6 | Newest features, async perf, current wheels |
| Core engine | **pytsk3** as the single FS reader | Covers NTFS, FAT16/32, exFAT, EXT2/3/4, HFS+; actively maintained |
| NTFS | via pytsk3 (not pyfsntfs) | pyfsntfs is unavailable on PyPI |
| exFAT | pytsk3 (TSK >=4.4 supports it) | Removes need for pyfatfs as primary; keep pyfatfs as optional reader |
| ReFS | **Carve-only** (raw sector scan) | TSK has no ReFS support |
| Windows magic | `python-magic-bin` (bundles `magic1.dll`) with extension-based fallback | Avoids manual DLL installation |
| Charts | **Custom QPainter rings/gauges** for Dashboard; Qt Charts optional | Full design control, smaller footprint |
| WebEngine | **Deferred** to post-v1 | Heavy; not needed for native UI |
| Preview | PyMuPDF (PDFs), Pillow (images), `python-docx`/`openpyxl` (Office), plain-text/source viewer, ffmpeg (video thumbnails) | All wheels available |
| Concurrency | Hybrid: TSK releases the GIL -> metadata scans in threads; raw sector carving -> **worker processes** (each opens its own TSK image handle over a sector range), single SQLite-writer aggregator | Safe TSK usage + no DB lock contention |
| Packaging | PyInstaller + Inno Setup, with a pytsk3 hook | Reliable Windows distribution |
| Fonts | Inter (OFL) + Segoe UI Variable; JetBrains Mono for data | SF Pro not licensable |
| Database | SQLite (WAL mode) | Offline, robust, schema below |

## 2. Repository Layout

```
Rescuer/
├── main.py                      # dev entrypoint
├── pyproject.toml               # deps, entry points, build config
├── requirements.txt
├── rescuer/
│   ├── entrypoint.py            # bootstrap: single-instance, admin check, splash
│   ├── constants.py / paths.py / exceptions.py
│   ├── core/                    # app_context, config, theme, event_bus,
│   │                            # worker_pool, database(+migrations), logging
│   ├── ui/
│   │   ├── main_window.py, navigation.py, animations.py
│   │   ├── widgets/             # ring, cards, progress, skeleton, toasts, searchbar
│   │   ├── pages/               # dashboard, drives, wizard, results,
│   │   │                        # preview, queue, reports, settings
│   │   └── resources/           # icons, QSS themes, fonts
│   ├── engine/
│   │   ├── device/              # Win32 device detection, health, interface info
│   │   ├── fs/                  # TSK wrappers (Img/Vol/FS abstraction)
│   │   ├── scan/                # quick, deep, signature, partition scans
│   │   ├── carve/               # file carver (worker processes)
│   │   ├── signatures/          # loader + matcher
│   │   ├── preview/             # per-type renderers + thumbnail cache
│   │   ├── quality/             # Recovery Quality Analyzer
│   │   ├── recovery/            # recovery processor + queue engine
│   │   ├── imaging/             # IMG/DD/E01 read + create-image
│   │   └── partition/           # MBR/GPT analyzer
│   ├── services/                # sessions, reports, search, assistant, vault
│   ├── integrations/            # windows/, ffmpeg.py, magic.py
│   └── data/                    # signatures.json, sql migrations
├── tests/                       # unit / integration / fixtures (sample images)
└── packaging/                   # pyinstaller spec + hooks, installer script
```

## 3. Data Model (SQLite, WAL mode)

- **drives** — device_id, label, fs_type, serial, capacity, used/free, health, is_ssd, bus_type, interface, last_scan_at
- **scans** — drive_id, mode (quick/deep/signature/partition), status, filters_json, start/end, duration_ms, found/recovered counts, sectors_scanned, errors
- **files** — scan_id, name, ext, size, is_deleted, deleted_at/created_at, fs_type, cluster, found_by, raw_offset, **quality_score**, **confidence**, status (new/recovered/failed/queued), thumb_path, sha256 — indexed on (scan_id), (name), (ext), (quality_score)
- **queue** — file_id, priority, status, added/recovered_at
- **recoveries** — scan_id, file_id, dest_path, status, bytes_written, hash_match
- **sessions** — name, scan_id, snapshot_json, resumed_at
- **vault** — folder, added_at, metadata_json
- **reports**, **settings**, **events** (log stream)

Lazy-loading: scan results stream into `files` in batches; UI pages query on demand (virtualized table).

## 4. Recovery Engine Design

**Scan pipeline (all modes):**
1. **Select target** -> disk, volume, or image file
2. **Analyze** -> partition table (MBR/GPT), filesystem type, size
3. **Scan** -> mode-specific producer
4. **Aggregate** -> candidates written to SQLite with metadata
5. **Score** -> quality analyzer runs per candidate
6. **Preview/Recover** -> on demand

**Mode implementation:**
- **Quick Scan** — TSK filesystem walk; recovers entries marked deleted + recycle-bin (`$I`/`$R`) parsing on NTFS; metadata reconstruction.
- **Deep Scan** — signature scan over the whole raw image; workers split into sector ranges; each process opens its own `Img_Info`; **file carving** with header+footer+max-gap; cluster continuity checks when adjacent free clusters allow.
- **Signature Scan** — carve-only variant; extensible.
- **Partition Recovery** — scan for boot sectors / partition-table signatures (NTFS `NTFS    `, FAT, exFAT) to rebuild lost partitions.
- **Image Recovery** — read from IMG/DD raw, E01 via `ewf`/`libewf-python` (optional, later phase).

**Signature database (`data/signatures.json`) — data-driven, no code changes to add formats:**
```json
{ "id": "pdf", "extensions": [".pdf"], "category": "documents",
  "header": {"bytes": "25504446", "offset": 0},
  "footer": {"bytes": "2525454F46", "max_gap": 65536},
  "min_size": 100, "carve": true, "preview": "pdf" }
```
Categories: documents, photos, videos, audio, archives, databases, CAD, design, VM images, source code, email. Ship ~150+ signatures; matcher supports offset, multi-signature, footer gap, and size heuristics.

## 5. Recovery Quality Analyzer (score -> stars)

Weighted heuristics -> **0–100**: metadata source (intact FS entry = high), name/path recovery, header match confidence, footer present (for bounded formats), size sanity, parse-test on preview (e.g., PDF opens, image header valid, archive integrity), fragmentation/carve completeness, dedup hash.

| Score | Stars |
|---|---|
| 90–100 | Excellent (5 stars) |
| 75–89 | Good (4 stars) |
| 50–74 | Partial (3 stars) |
| 25–49 | Damaged (2 stars) |
| 0–24 | Poor (1 star) |

Shown with a confidence % and a plain-language explanation (e.g., "No footer found — last sector(s) may be missing").

## 6. UI Design System

- **Theme tokens** in QSS + a palette module (Dark default, Light toggle): background `#0B0E14` (Deep Space Black), accent Electric Blue `#2E8CFF`, Emerald `#2ECB85`, success Bright Green, Amber warning, Crimson error.
- **Components**: navigation rail with animated page transitions, storage rings & gauges (QPainter), card hover-lift, ripple buttons, animated progress, skeleton loading, toasts, drag-and-drop (into queue/preview), keyboard shortcuts, dockable panels with persisted layouts.
- **Pages**: Dashboard -> Drive Manager -> Recovery Wizard (step sidebar: Select device -> Scan mode -> Filters -> Scan -> Preview -> Recover -> Report) -> Results Explorer (virtualized, instant filtering) -> Preview Panel -> Recovery Queue -> Reports -> Settings.

## 7. Concurrency Model

- **UI thread**: Qt event loop; all engine calls offloaded.
- **QThreadPool**: previews, thumbnails, hashing, reports.
- **Scan workers**: quick/metadata scans in a `QThread` (TSK releases the GIL); deep/carve scans via **`ProcessPoolExecutor`** splitting sector ranges, each process opening its own image handle -> results to an aggregator task that owns all SQLite writes -> progress events throttled to ~10 Hz to the UI.

## 8. Security & Reliability

Read-only scanning by default; admin/elevation detection (`pywin32` + manifest); optional SHA-256 integrity verification at recovery; scan metadata auto-backup; settings stored in `%APPDATA%` (encrypt sensitive values with Windows DPAPI); detailed rotating logs; never write to the source volume — **warn + block** saving recovered files to the same drive (Smart Assistant rule).

## 9. Packaging & Distribution

- PyInstaller spec with a custom hook for pytsk3 DLLs; Inno Setup installer (installer for 10/11, x64); auto-update via embedded update check (Phase 5); optional portable build.

## 10. Roadmap with Acceptance Criteria

**Phase 0 — Bootstrap (0.5 wk)** · repo, pyproject, CI, logging, exceptions, single-instance, admin detection, package skeleton. *AC: `python main.py` opens dark-themed shell; logs to file.*

**Phase 1 — Foundation (2 wks)** · theme system, navigation, dashboard, settings, DB schema, **device detection** (GetLogicalDrives, SetupAPI storage classes, volume FS info, SMART via IOCTL with PowerShell fallback, SSD/HDD & bus detection). *AC: all drives listed with capacity/FS/health/interface; dashboard renders live stats.*

**Phase 2 — Recovery Engine (4 wks)** · TSK wrappers, Quick Scan (NTFS/FAT/exFAT + recycle bin), Deep Scan, signature scanning + carver, partition analysis, recovery processor. *AC: recover emptied recycle bin; recover a formatted USB; carve files by header from a wiped volume.*

**Phase 3 — Preview & Analysis (2.5 wks)** · thumbnails (Pillow/PyMuPDF/ffmpeg), preview panel, quality scoring, advanced search, Smart Assistant rules (best-scan recommendation, same-drive warning, duplicate detection, priority sorting). *AC: previews for images/PDF/Office/text/video-thumbs; scores + explanations shown; filters fast on 100k+ rows.*

**Phase 4 — Productivity (2 wks)** · reports (PDF via reportlab/HTML/CSV), session save/resume, disk imaging (create + read IMG/DD, E01 later), recovery queue (pause/resume/prioritize, batch), export tools. *AC: full wizard flow end-to-end with a report generated; session resumes without rescan.*

**Phase 5 — Premium & Release (2 wks)** · animation/performance polish, accessibility (keyboard nav, contrast, screen-reader labels), plugin manager, installer, auto-update, comprehensive test pass. *AC: shipped installer; smoke-tested recovery on fixtures; UI benchmark (scroll + filter) meets targets.*

## 11. Risks & Mitigations

- **pytsk3 wheel for Py 3.14/win64** — verify at Phase 0; fallback: build from source (MSVC) or pin Python 3.13 for the build.
- **Windows raw access** needs elevation for full-disk work — clear elevation prompts; volume scans work elevated-friendly.
- **Antivirus interference** slows scans — document whitelisting; chunked I/O keeps responsiveness.
- **ReFS/APFS unsupported** by TSK — carve-only paths; APFS deferred.
- **PyInstaller + pytsk3** — dedicated hook + runtime smoke test on clean VM.

## 12. Time Estimate

Total: **~13–16 weeks** solo full-time.

| Phase | Scope | Estimate |
|---|---|---|
| 0 – Bootstrap | repo, config, logging, packaging skeleton | 0.5 wk |
| 1 – Foundation | theme, navigation, dashboard, settings, DB, device detection | 2–3 wks |
| 2 – Recovery Engine | TSK readers, Quick/Deep/Signature scans, carving, recovery | 4–5 wks |
| 3 – Preview & Analysis | thumbnails, previews, quality scoring, search, assistant | 2.5–3.5 wks |
| 4 – Productivity | reports, sessions, imaging, queue, export | 2–2.5 wks |
| 5 – Premium & Release | polish, accessibility, plugins, installer, auto-update, testing | 2–3 wks |

MVP-only (Quick + Deep scans, previews, basic reports): **~6–8 weeks**. Part-time: roughly double.
