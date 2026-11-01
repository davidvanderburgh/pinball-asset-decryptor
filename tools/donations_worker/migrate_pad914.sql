-- PAD-914: the app's Your reports board.  Run ONCE on a database made
-- before it (schema.sql's CREATE TABLE IF NOT EXISTS leaves an existing
-- table as it was):
--   npx wrangler d1 execute pad-donations --remote --file migrate_pad914.sql
-- A second run fails on "duplicate column name", which is harmless.
ALTER TABLE reports ADD COLUMN stage    TEXT    NOT NULL DEFAULT '';
ALTER TABLE reports ADD COLUMN ticket   TEXT    NOT NULL DEFAULT '';
ALTER TABLE reports ADD COLUMN progress INTEGER NOT NULL DEFAULT -1;
ALTER TABLE reports ADD COLUMN stage_at INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN seen_at  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN install  TEXT    NOT NULL DEFAULT '';
