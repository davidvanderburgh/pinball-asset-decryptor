-- The donations table (PAD-754).  One row per donation a user reported.
-- `usd` is the amount converted when it was reported and never changes;
-- `removed` hides a row from the total without losing it.
CREATE TABLE IF NOT EXISTS donations (
  id          TEXT PRIMARY KEY,
  at          INTEGER NOT NULL,
  amount      REAL    NOT NULL,
  currency    TEXT    NOT NULL,
  usd         REAL    NOT NULL,
  shelter     TEXT    NOT NULL DEFAULT '',
  country     TEXT    NOT NULL DEFAULT '',
  region      TEXT    NOT NULL DEFAULT '',
  name        TEXT    NOT NULL DEFAULT '',
  show_name   INTEGER NOT NULL DEFAULT 0,
  app_version TEXT    NOT NULL DEFAULT '',
  ip_hash     TEXT    NOT NULL DEFAULT '',
  removed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS donations_at ON donations (at);
CREATE INDEX IF NOT EXISTS donations_ip ON donations (ip_hash, at);
