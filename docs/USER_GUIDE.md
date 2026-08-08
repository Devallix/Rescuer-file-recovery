# Rescuer User Guide

Rescuer is a professional file-recovery and data-restoration suite for Windows 10/11. This guide explains how to use the application end to end.

---

## 1. Getting Started

### Installation

```powershell
pip install -r requirements.txt
python main.py
```

Requirements: Windows 10/11 x64, Python 3.13 or newer.

### Running as Administrator

Reading a raw volume or scanning certain system areas requires **elevated privileges**. For best results:

- Right-click your terminal and choose **Run as administrator**, then run `python main.py`, **or**
- Launch the app normally for folder/image scans (no elevation needed).

The status bar shows whether you are running as an **Administrator** or **Standard user**.

> **Important:** Standard scans are read-only. Rescuer never writes to the drive being scanned.

---

## 2. The Interface

The navigation rail on the left switches between the main areas:

| Page | Purpose |
| ---- | ------- |
| **Dashboard** | Storage overview, quick actions, and step-by-step recovery guide |
| **Drives** | List every connected volume, run scans, create disk images |
| **Recovery Wizard** | Guided recovery: device → scan → review → recover → report |
| **Results** | Browse, filter, preview, and search files found by previous scans |
| **Reports** | Generate and open recovery reports |
| **Settings** | Theme, scan defaults, updates, signatures, and general options |

### Keyboard shortcuts

- `Ctrl+1` Dashboard · `Ctrl+2` Drives · `Ctrl+N` Recovery Wizard · `Ctrl+3` Results · `Ctrl+4` Reports · `Ctrl+,` Settings
- `F1` opens the **About** dialog.

### Help menu

The **Help** menu in the menu bar provides:

- **User Guide** — opens this document.
- **About** — version and build information.
- **Developer** — developer credits.
- **End User License Agreement** — the license text.

### System tray

Rescuer keeps running in the system tray when you close the window:

- Closing the window hides it to the tray (it does not quit). Choose **Quit** from the tray menu to exit fully.
- Scans continue in the background while hidden, and you get a **notification** when a scan finishes or fails.
- The tray menu shows the number of scans in progress and a **scan count**; clicking the icon opens the window again.

---

## 3. Recovering a Deleted File — Step by Step

Follow these steps to recover a file you deleted. **Act quickly — the sooner you stop using the drive, the better your chances.**

1. **Stop using the drive.** Do not save anything new to the drive the file was on, and avoid rebooting if possible.
2. **Choose a source.**
   - Open the **Recovery Wizard** (or click **Quick Scan** on the Dashboard).
   - Select the drive the file was on, or click **Load disk image…** to work on an image file instead of a live drive.
   - You can also click **Scan a folder…** to scan just one folder, or select **multiple drives** at once (hold `Ctrl` or `Shift`) to scan them in parallel.
3. **Pick a scan method.**
   - **Quick scan** — uses filesystem metadata to list recently deleted files. Fast, best first attempt.
   - **Deep scan** — carves whole drives for files by their signatures (JPEG, PDF, ZIP, …). Slower but finds more.
   - **Partition analysis** — inspects MBR/GPT structures and boot sectors.
   - Adjust **Carve workers** (1–8) to trade scan speed against CPU load during deep scans.
   - Optionally tick **Verify recovered files with SHA-256** for integrity checking.
4. **Let the scan run.** Watch the progress bar and candidate counter on the **Scanning** step. Cancel anytime.
5. **Review candidates.** On the **Review** step, filter with the search box, inspect **quality stars**, and pick the files that match.
6. **Choose a destination.** Pick a saved **vault** folder from the dropdown, type a folder (default: `~/Recovered Files`), or click **…** to browse. Use a **different drive** than the one being recovered.
7. **Recover.** Click **Recover selected** or **Recover all**. Progress appears on the **Complete** step.
8. **Export a report.** Generate an **HTML**, **PDF**, or **CSV** report of the operation, then click **Open output folder** to inspect your files.

---

## 4. Quick Actions (Dashboard)

- **New Recovery Wizard** — opens the guided wizard.
- **Quick Scan** — opens the wizard, pre-selects **Quick** mode, and starts a quick scan on the first detected volume automatically.
- **Scan Folder** — pick a folder on a local drive and run a quick scan of it for deleted files.
- **Create Disk Image** — jumps to the **Drives** page so you can image a selected volume.
- **Toggle theme** — switches between dark and light appearance.

---

## 5. Folder Scans

You don't always need to scan a whole volume. Use **Scan a folder…** in the wizard (or the **Scan Folder** quick action) to target a single folder on a local drive.

- Folder scans are fast and read-only, and work without administrator rights.
- They use **quick scan** metadata logic, listing deleted files the filesystem still knows about.
- Files deleted with the **Delete** key are moved to the Recycle Bin rather than removed from the folder, so they do not appear in a folder scan. If nothing is found, the wizard explains this and offers a **Recycle Bin scan** for that drive instead.

---

## 6. Understanding Results

Each candidate shows:

- **Name / Type / Size** — basic file information.
- **Quality** — a 1–5 star rating computed from detection strength, integrity checks, file size, filename match, and hash verification. 5 stars = excellent, 1 = uncertain.
- **Confidence** — percentage from the recovery-quality analyzer.
- **Method** — how it was found: `FS` (filesystem metadata), `Carved` (deep signature scan), or `Recycle` (recycle-bin entry).
- **Status** — lifecycle state (`new`, `queued`, `processing`, `done`, `failed`, `skipped`).

### Results Explorer

The **Results** page adds powerful browsing on top of the scan list:

- **Type chips** — quickly filter to Images, Documents, Video, Audio, Archives, or Other.
- **Min score / Min size / Max size** — numeric filters.
- **Deleted only** — show only deleted entries.
- **Duplicates only** — show files that share an identical SHA-256 with another candidate.
- **Live preview** — click a row to preview images, PDFs, Office documents, text, and more in the side panel; double-click a row for full file details (path, inode, raw offset, SHA-256, timestamps, …).
- **Right-click a row** to copy its path or filename.
- **Export CSV** — save the current filtered view to a CSV file.
- **Recover selected** — queue selected files for recovery directly from the results table.

### Search & Smart Assistant

The search box supports:

- Plain text — `holiday`
- Extension filter — `ext:jpg`
- Minimum quality — `min:70`
- Combined — `ext:pdf min:75 deleted:yes`

The assistant understands intent, e.g. *"images deleted last week"*, and merges matching filters automatically.

---

## 7. Recovery Queue

When you start recovery, jobs run in the background so the interface stays responsive.

- **Start** — begin processing queued files for a chosen scan.
- **Stop** — cancel gracefully; already recovered files are kept.
- **Stats** — pending / done / failed counters update live.
- Duplicate content (identical SHA-256) is automatically **skipped** and recorded.

---

## 8. Sessions

On the **Complete** step of the wizard, click **Save session** to store a named snapshot of the finished scan (device, mode, category counts, and top-quality files) in your local database. Sessions are kept so scan results can be revisited later without re-running the scan.

---

## 9. Vaults

Vaults are saved recovery-destination folders that appear in the **Recover to:** dropdown on the Review step. Pick a previously saved vault, or choose **Custom folder…** to type a new destination. This keeps your favourite output locations one click away.

---

## 10. Reports

Open the **Reports** page to generate a report for any completed scan:

- **CSV** — spreadsheet-friendly row data.
- **HTML** — human-readable document, opens in your browser.
- **PDF** — printable copy (via ReportLab).

Reports live in your Rescuer data folder and can be reopened from the reports list. Double-click a report row to open it.

---

## 11. Disk Imaging

Creating a byte-for-byte image of a volume lets you work on a static copy instead of a live drive.

1. Go to **Drives** and select a volume.
2. Click **Create image…** and choose an output location.
3. Confirm the warning, then wait — large drives take a long time.
4. Load the resulting `.img` in the wizard via **Load disk image…**.

> Raw `\\.\` volume reads require **administrator** rights.

---

## 12. Recycle Bin Recovery

Deleted files still present in the Windows Recycle Bin can be recovered directly, including their **original paths** and **deletion dates**.

- Run a **Recycle** scan over `$Recycle.Bin` (this mode is part of the scan engine; files found appear with method `Recycle`).
- Large recycled files stored in the `$R` container format are expanded automatically.

### When direct scanning is blocked

Raw `\\.\` volume access requires **administrator** rights. If a quick/deep scan cannot start because access was denied, the app explains why and offers a **Recycle Bin scan instead**:

- A **prompt** appears in the wizard asking whether to scan the Recycle Bin, and the **Dashboard** shows a banner with the reason plus a *Scan Recycle Bin instead* button.
- To scan the volume directly, **close the app and reopen it as administrator**, then run the scan again.
- Recycle scans work as a standard user — no elevation needed.

### Restoring files to their original location

On the Review step, tick **“Restore Recycle Bin files to their original locations”** to put recycled files back where they were deleted from, using their original folder and name. Unticked, files go to the destination folder chosen in “Recover to:”.

---

## 13. Auto-Updates

Rescuer can update itself when a new version is released.

- By default the app **checks for updates automatically** on startup (disable this in Settings → Updates).
- **Update endpoint** — the URL of the manifest file that lists the latest version and the ZIP to download. Point this at the hosted `manifest.json`.
- **Channel** — which release channel to follow: `stable`, `beta`, or `dev`.
- **Check now** — run an update check immediately. When an update is available you are asked whether to download and install it; the app restarts automatically and rolls back if anything goes wrong.

---

## 14. Plugins

Plugins extend the engine with custom hooks such as `scan_started`, `scan_finished`, `found`, and `recovery_started`/`recovery_finished`.

- Drop a plugin module (`*.py` or a folder containing `plugin.py`) into the Rescuer **plugins** directory (created next to the app data).
- A plugin exposes a `Plugin` class (subclassing `RescuerPlugin`), a `plugin` instance, or a `setup()` function.
- Enable/disable plugins from the settings; a broken plugin is skipped and logged without stopping the app.

---

## 15. Settings

| Setting | Purpose |
| ------- | ------- |
| Theme | Dark / light appearance (apply immediately) |
| Check for updates automatically | Run an update check on startup |
| Update endpoint | URL of the hosted update manifest (`manifest.json`) |
| Channel | Update channel to follow (`stable`, `beta`, `dev`) |
| Custom signatures folder | Optional folder with extra signature files for carving |
| Delete scans older than 30 days | One-click cleanup of old scan history |

---

## 16. Tips for Success

- **Act fast.** Continued use of the source drive overwrites deleted data.
- **Recover to a different drive** to avoid overwriting the very data you need.
- **Deep scan** when a quick scan finds nothing — it examines the raw device.
- **Verify hashes** on critical files so you know the bytes match.
- **Image first** for long jobs; scan the image repeatedly without touching the original drive.
- **Report after recovery** to keep a record of what was found and recovered.
- **Save a session** after big scans so you can return to the results later.

---

## 17. FAQ

**Nothing was found on a quick scan.**
Run a deep scan, or check the Recycle Bin for the drive.

**Recovery failed for a file.**
The source clusters may have been overwritten. Try a different scan mode or image sooner next time.

**The app asks for administrator rights.**
Raw volume access needs elevation. When a scan is blocked, the app offers a **Recycle Bin scan** that works without admin rights — or restart the app as administrator for full raw scanning.

**Why is a candidate marked `skipped`?**
Its content (SHA-256) was already recovered earlier in the same queue run.

**Where are reports and recovered files?**
Recovered files go to the destination you chose; reports are saved to your Rescuer data folder and listed in the Reports page.

**The window closed but the app is still running.**
That's the system tray — closing the window hides Rescuer so scans can finish. Use the tray menu to reopen or quit.

**How do I install an update?**
Make sure the **Update endpoint** in Settings points at your hosted `manifest.json`, then click **Check now** (or wait for the automatic check). Accept the prompt to download and install.
