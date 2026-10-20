"""SQLite storage for passes and their positions."""

import math
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- One row for each time an aircraft crosses the capture area.
CREATE TABLE IF NOT EXISTS passes (
  id INTEGER PRIMARY KEY,
  hex TEXT NOT NULL,
  flight TEXT,
  category TEXT,
  start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL,
  min_ts INTEGER NOT NULL,       -- time of closest approach
  min_dist_m INTEGER NOT NULL,   -- horizontal distance at closest approach
  min_alt_ft INTEGER,            -- altitude at closest approach
  points INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS passes_min_ts ON passes (min_ts);
CREATE INDEX IF NOT EXISTS passes_end_ts ON passes (end_ts);

CREATE TABLE IF NOT EXISTS positions (
  pass_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  lat_e5 INTEGER NOT NULL,
  lon_e5 INTEGER NOT NULL,
  alt_ft INTEGER,
  PRIMARY KEY (pass_id, ts)
) WITHOUT ROWID;
"""

EARTH_RADIUS_M = 6371008.8


class Home:
    """A local flat projection around the receiver, in metres.

    Within the capture radius (tens of km) the error is far below the
    accuracy of an ADS-B position.
    """

    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon
        self._kx = math.radians(1) * EARTH_RADIUS_M * math.cos(math.radians(lat))
        self._ky = math.radians(1) * EARTH_RADIUS_M

    def xy(self, lat, lon):
        return (lon - self.lon) * self._kx, (lat - self.lat) * self._ky


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    return db


def init(path):
    db = connect(path)
    db.executescript(SCHEMA)
    db.commit()
    return db


def get_meta(db, key):
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))
    db.commit()


def prune(db, before_ts):
    """Delete passes that ended before `before_ts`, with their positions."""
    db.execute(
        "DELETE FROM positions WHERE pass_id IN (SELECT id FROM passes WHERE end_ts < ?)",
        (before_ts,),
    )
    n = db.execute("DELETE FROM passes WHERE end_ts < ?", (before_ts,)).rowcount
    db.commit()
    return n
