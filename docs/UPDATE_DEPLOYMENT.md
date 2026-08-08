# Update Deployment Guide

Guide for deploying `releases/Rescuer_0.1.1.zip` so the built-in updater works.

## 1. What the updater expects

The app is a three-piece pipeline (`rescuer/engine/updates/`):

1. **Check** — `check_for_updates()` GETs your `updates.endpoint` and parses a JSON manifest.
2. **Download** — `download_update()` streams from `info.url` (shows a progress bar; requires the server to send a `Content-Length` header).
3. **Install** — `verify_sha256()` (if provided) → the app quits → a detached `.bat` renames the install folder aside, extracts the zip over the original path, relaunches, and self-deletes. Rollback if the zip is bad.

## 2. Host the zip + a manifest

Put both on any static HTTPS host (GitHub Releases, S3, Cloudflare R2, or a plain web server). The **manifest must be a JSON file** with exactly these keys:

```json
{
  "version": "0.1.1",
  "url": "https://your-host.example.com/rescuer/Rescuer_0.1.1.zip",
  "sha256": "85050B8B79E81DF953DEA3C90794C4418C03EE634A366AD498DF8901367BEE58",
  "size_bytes": 80792385,
  "notes": "Scan Folder quick action; updater fixes",
  "published_at": "2026-08-08 15:30:51"
}
```

The checker reads `data.get("version")`, `"url"`, `"notes"`, `"published_at"`, `"size_bytes"`, `"sha256"`. If `version` matches the running version, no update is offered. If `sha256` is missing, verification is skipped (include it).

> **Important:** the default endpoint is `https://api.github.com/repos/rescuer-app/rescuer/releases/latest` (GitHub's API schema). That response does **not** match this manifest format, so point the app at your own manifest URL (see step 4).

## 3. Zip layout — don't change it

The zip must contain `Rescuer.exe` **and** `_internal/` at the **root** — exactly the contents of `dist/Rescuer\*`. The swap batch extracts the zip into the existing install folder, so a nested `Rescuer/Rescuer.exe` path would break the relaunch. The current `releases/Rescuer_0.1.1.zip` is already in the correct layout; don't re-zip it with an outer folder.

## 4. Point the app at your endpoint

The endpoint is stored in the app config (Settings → Updates → "Update endpoint", or the DB `config` table key `updates.endpoint`). Do **one** of:

- **New installs:** change the default in `rescuer/core/database.py:97` to your manifest URL (e.g. `https://your-host.example.com/rescuer/manifest.json`). Note this only applies to DBs created afterward.
- **Already-deployed 0.1.0 clients:** they already have the old GitHub default in their DB, so update the endpoint on the Settings page, or ship a config migration.

## 5. Install location requirement

The updater renames the **install folder's parent** and writes `rescuer_updater_*.bat` there, then extracts the zip — so the app must **not** be inside `C:\Program Files` (standard users can't rename/create there). Install to a user-writable folder, e.g. `C:\Rescuer\` or `%LocalAppData%\Rescuer\`. If the rename/extract fails, the batch rolls back to the previous version automatically.

## 6. Verify the update

1. On a machine running 0.1.0 (or set version `0.1.0` in the manifest temporarily to test the "already running 0.1.1" logic).
2. Settings → set the endpoint to your manifest → "Check for updates".
3. Accept the prompt → watch the progress dialog → app quits, the swap runs, the new 0.1.1 window opens.
4. Confirm `releases/Rescuer_0.1.1.zip` is deleted from the cache after the swap and no `Rescuer.old_*` folders are left.

**Version rule:** manifest `version` must sort higher than the installed one (`0.1.1 > 0.1.0` works; plain string compare is used, so keep numeric versions consistent, e.g. `0.10.0 > 0.9.9` but `0.1.10` would compare less than `0.1.2`).
