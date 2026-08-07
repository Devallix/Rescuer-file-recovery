PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS drives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT UNIQUE,
    mount_point TEXT,
    label TEXT,
    file_system TEXT,
    serial TEXT,
    capacity INTEGER DEFAULT 0,
    used_bytes INTEGER DEFAULT 0,
    free_bytes INTEGER DEFAULT 0,
    is_removable INTEGER DEFAULT 0,
    is_ssd INTEGER DEFAULT 0,
    bus_type TEXT,
    interface TEXT,
    health TEXT,
    model TEXT,
    last_scan_at TEXT
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_id INTEGER REFERENCES drives(id),
    device_id TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    filters_json TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER DEFAULT 0,
    found_count INTEGER DEFAULT 0,
    recovered_count INTEGER DEFAULT 0,
    sectors_scanned INTEGER DEFAULT 0,
    errors_json TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    ext TEXT,
    path TEXT,
    size INTEGER DEFAULT 0,
    is_deleted INTEGER DEFAULT 0,
    created_at TEXT,
    deleted_at TEXT,
    modified_at TEXT,
    fs_type TEXT,
    cluster INTEGER,
    inode INTEGER,
    found_by TEXT,
    raw_offset INTEGER,
    quality_score INTEGER,
    confidence INTEGER,
    quality_explanation TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    thumb_path TEXT,
    sha256 TEXT,
    original_drive_id TEXT,
    duplicate_of INTEGER REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_files_scan ON files(scan_id);
CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);
CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_quality ON files(quality_score);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);

CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    priority INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    added_at TEXT,
    recovered_at TEXT
);

CREATE TABLE IF NOT EXISTS recoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    file_id INTEGER REFERENCES files(id),
    dest_path TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    bytes_written INTEGER DEFAULT 0,
    hash_match INTEGER,
    error TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    scan_id INTEGER REFERENCES scans(id),
    snapshot_json TEXT,
    created_at TEXT,
    resumed_at TEXT
);

CREATE TABLE IF NOT EXISTS vault (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL UNIQUE,
    added_at TEXT,
    metadata_json TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    report_type TEXT NOT NULL,
    path TEXT NOT NULL,
    generated_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level TEXT NOT NULL,
    source TEXT,
    scan_id INTEGER,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_scan ON events(scan_id);
