ALTER TABLE files ADD COLUMN signature_id TEXT;
ALTER TABLE files ADD COLUMN footer_found INTEGER DEFAULT 0;
ALTER TABLE files ADD COLUMN category TEXT;
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
CREATE INDEX IF NOT EXISTS idx_files_signature ON files(signature_id);
