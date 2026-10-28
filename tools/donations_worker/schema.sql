-- The donations table (PAD-754).  One row per donation a user reported.
-- `usd` is the amount converted when it was reported and never changes;
-- `held` keeps a big entry out of the total until David approves it;
-- `removed` hides a row from the total without losing it; `ip_hash` (a
-- salted hash of the sender's address, for the five-an-hour limit) is
-- blanked once the row is an hour old.
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
  edit_token  TEXT    NOT NULL DEFAULT '',
  held        INTEGER NOT NULL DEFAULT 0,
  removed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS donations_at ON donations (at);
CREATE INDEX IF NOT EXISTS donations_ip ON donations (ip_hash, at);

-- Problem reports (PAD-780).  One row per Report a problem the app sent:
-- the record as the user saw it before sending, a shrunk picture if they
-- added one, and the name they typed (optional; never an address).  Once
-- David's tracker takes it (/taken) everything they wrote is blanked and
-- the row is only a `state`: filed, then released (with the version and
-- David's message) or closed, which the app that sent it reads back to
-- tell the user; an answered row is dropped after 90 days.  `ip_hash` is
-- for the five-an-hour limit and is blanked after an hour, as above.
CREATE TABLE IF NOT EXISTS reports (
  id           TEXT PRIMARY KEY,
  at           INTEGER NOT NULL,
  app_version  TEXT    NOT NULL DEFAULT '',
  platform     TEXT    NOT NULL DEFAULT '',
  title        TEXT    NOT NULL DEFAULT '',
  body         TEXT    NOT NULL DEFAULT '',
  name         TEXT    NOT NULL DEFAULT '',
  picture_type TEXT    NOT NULL DEFAULT '',
  picture      TEXT    NOT NULL DEFAULT '',
  ip_hash      TEXT    NOT NULL DEFAULT '',
  state        TEXT    NOT NULL DEFAULT 'received',
  version      TEXT    NOT NULL DEFAULT '',
  message      TEXT    NOT NULL DEFAULT '',
  answered_at  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS reports_at ON reports (at);
CREATE INDEX IF NOT EXISTS reports_ip ON reports (ip_hash, at);
