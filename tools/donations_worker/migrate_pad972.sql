-- PAD-972: questions to the reporter, answered in the app.  Run ONCE on a
-- database made before it (schema.sql's CREATE TABLE IF NOT EXISTS leaves
-- an existing table as it was), then deploy:
--   npx wrangler d1 execute pad-donations --remote --file migrate_pad972.sql
--   npx wrangler deploy
-- A second run fails on "duplicate column name", which is harmless.
CREATE TABLE IF NOT EXISTS reply_log (
  ip_hash TEXT    NOT NULL,
  at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS reply_log_ip ON reply_log (ip_hash, at);
ALTER TABLE reports ADD COLUMN question      TEXT    NOT NULL DEFAULT '';
ALTER TABLE reports ADD COLUMN question_at   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN reply         TEXT    NOT NULL DEFAULT '';
ALTER TABLE reports ADD COLUMN reply_files   TEXT    NOT NULL DEFAULT '[]';
ALTER TABLE reports ADD COLUMN reply_at      INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN reply_pending INTEGER NOT NULL DEFAULT 0;
