-- Earlier builds defaulted to the GitHub releases API, which returns a different
-- JSON schema (and the repo path no longer exists), so the updater could never
-- discover a release. Point those installs at the repository manifest instead.
-- The previously proposed raw.githubusercontent.com URL is normalised too.
UPDATE settings
SET value = '"https://github.com/Devallix/Rescuer-file-recovery/raw/refs/heads/main/manifest.json"'
WHERE key = 'updates.endpoint'
  AND value IN (
      '"https://api.github.com/repos/rescuer-app/rescuer/releases/latest"',
      '"https://raw.githubusercontent.com/Devallix/Rescuer-file-recovery/main/manifest.json"'
  );
