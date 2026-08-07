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
| **Results** | Browse and search files found by previous scans |
| **Recovery Queue** | Manage background recovery jobs and their progress |
| **Reports** | Generate and open recovery reports |
| **Settings** | Theme, scan defaults, verification, and general options |

---

## 3. Recovering a Deleted File — Step by Step

Follow these steps to recover a file you deleted. **Act quickly — the sooner you stop using the drive, the better your chances.**

1. **Stop using the drive.** Do not save anything new to the drive the file was on, and avoid rebooting if possible.
2. **Choose a source.**
   - Open the **Recovery Wizard** (or click **Quick Scan** on the Dashboard).
   - Select the drive the file was on, or click **Load disk image…** to work on an image file instead of a live drive.
3. **Pick a scan method.**
   - **Quick scan** — uses filesystem metadata to list recently deleted files. Fast, best first attempt.
   - **Deep scan** — carves whole drives for files by their signatures (JPEG, PDF, ZIP, …). Slower but finds more.
   - **Partition analysis** — inspects MBR/GPT structures and boot sectors.
   - Optionally tick **Verify recovered files with SHA-256** for integrity checking.
4. **Let the scan run.** Watch the progress bar and candidate counter on the **Scanning** step. Cancel anytime.
5. **Review candidates.** On the **Review** step, filter with the search box, inspect **quality stars**, and pick the files that match.
6. **Choose a destination.** Type a folder (default: `~/Recovered Files`) or click **…** to browse. Use a **different drive** than the one being recovered.
7. **Recover.** Click **Recover selected** or **Recover all**. Progress appears on the **Complete** step.
8. **Export a report.** Generate an **HTML**, **PDF**, or **CSV** report of the operation, then click **Open output folder** to inspect your files.

---

## 4. Quick Actions (Dashboard)

- **New Recovery Wizard** — opens the guided wizard.
- **Quick Scan** — opens the wizard, pre-selects **Quick** mode, and starts a quick scan on the first detected volume automatically.
- **Create Disk Image** — jumps to the **Drives** page so you can image a selected volume.

---

## 5. Understanding Results

Each candidate shows:

- **Name / Type / Size** — basic file information.
- **Quality** — a 1–5 star rating computed from detection strength, integrity checks, file size, filename match, and hash verification. 5 stars = excellent, 1 = uncertain.
- **Method** — how it was found: `FS` (filesystem metadata), `Carved` (deep signature scan), or `Recycle` (recycle-bin entry).
- **Status** — lifecycle state (`new`, `queued`, `processing`, `done`, `failed`, `skipped`).

### Search & Smart Assistant

The search box supports:

- Plain text — `holiday`
- Extension filter — `ext:jpg`
- Minimum quality — `min:70`
- Combined — `ext:pdf min:75 deleted:yes`

The assistant understands intent, e.g. *"images deleted last week"*, and merges matching filters automatically.

---

## 6. Recovery Queue

When you start recovery, jobs run in the background so the interface stays responsive.

- **Start** — begin processing queued files for a chosen scan.
- **Stop** — cancel gracefully; already recovered files are kept.
- **Stats** — pending / done / failed counters update live.
- Duplicate content (identical SHA-256) is automatically **skipped** and recorded.

---

## 7. Reports

Open the **Reports** page to generate a report for any completed scan:

- **CSV** — spreadsheet-friendly row data.
- **HTML** — human-readable document, opens in your browser.
- **PDF** — printable copy (via ReportLab).

Reports live in your Rescuer data folder and can be reopened from the reports list.

---

## 8. Disk Imaging

Creating a byte-for-byte image of a volume lets you work on a static copy instead of a live drive.

1. Go to **Drives** and select a volume.
2. Click **Create image…** and choose an output location.
3. Confirm the warning, then wait — large drives take a long time.
4. Load the resulting `.img` in the wizard via **Load disk image…**.

> Raw `\\.\` volume reads require **administrator** rights.

---

## 9. Recycle Bin Recovery

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

## 10. Plugins

Plugins extend the engine with custom hooks such as `scan_started`, `scan_finished`, `found`, and `recovery_started`/`recovery_finished`.

- Drop a plugin module (`*.py` or a folder containing `plugin.py`) into the Rescuer **plugins** directory (created next to the app data).
- A plugin exposes a `Plugin` class (subclassing `RescuerPlugin`), a `plugin` instance, or a `setup()` function.
- Enable/disable plugins from the settings; a broken plugin is skipped and logged without stopping the app.

---

## 11. Settings

| Setting | Purpose |
| ------- | ------- |
| Theme | Dark / light appearance (apply immediately) |
| Reduce motion / smart effects | Toggle animations and visual effects |
| Default scan mode | Which mode is pre-selected in the wizard |
| Show deleted only | Filter results to deleted entries by default |
| Verify hashes | Turn SHA-256 verification on/off for recoveries |
| Launch minimized | Start the app hidden to tray/background |

---

## 12. Tips for Success

- **Act fast.** Continued use of the source drive overwrites deleted data.
- **Recover to a different drive** to avoid overwriting the very data you need.
- **Deep scan** when a quick scan finds nothing — it examines the raw device.
- **Verify hashes** on critical files so you know the bytes match.
- **Image first** for long jobs; scan the image repeatedly without touching the original drive.
- **Report after recovery** to keep a record of what was found and recovered.

---

## 13. FAQ

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
