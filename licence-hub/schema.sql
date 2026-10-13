-- Licence hub (D1): online activation requests and owner-approved customers.
-- Poll tokens are stored hashed; signing keys never touch the database.

CREATE TABLE IF NOT EXISTS rate (
  key    TEXT NOT NULL,
  window INTEGER NOT NULL,
  count  INTEGER NOT NULL,
  PRIMARY KEY (key, window)
);

CREATE TABLE IF NOT EXISTS licence_requests (
  id              TEXT PRIMARY KEY,
  poll_token_hash TEXT NOT NULL,
  product         TEXT NOT NULL,
  kind            TEXT NOT NULL,
  device          TEXT NOT NULL,
  device_key      TEXT NOT NULL DEFAULT '',
  machine         TEXT NOT NULL,
  nonce           TEXT NOT NULL UNIQUE,
  shop            TEXT NOT NULL DEFAULT '',
  ref             TEXT NOT NULL DEFAULT '',
  version         TEXT NOT NULL DEFAULT '',
  status          TEXT NOT NULL,
  stage           TEXT NOT NULL DEFAULT '',
  reason          TEXT NOT NULL DEFAULT '',
  code            TEXT,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS licence_requests_status ON licence_requests(status, created_at);
CREATE INDEX IF NOT EXISTS licence_requests_device_open ON licence_requests(device_key, status);

CREATE TABLE IF NOT EXISTS machine_trials (
  machine    TEXT PRIMARY KEY,
  request_id TEXT,
  at         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
  id         TEXT PRIMARY KEY,
  shop       TEXT NOT NULL,
  device     TEXT NOT NULL,
  kind       TEXT NOT NULL,
  serial     TEXT,
  first_day  TEXT,
  last_day   TEXT,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS owner_sessions (
  id         TEXT PRIMARY KEY,
  csrf       TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
  ip     TEXT NOT NULL,
  window INTEGER NOT NULL,
  count  INTEGER NOT NULL,
  PRIMARY KEY (ip, window)
);
