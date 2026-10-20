"""Demo data: real tracks from the receiver, replayed over past days.

Every demo pass has a hex that starts with DEMO_PREFIX, which no real
aircraft address can have, so the demo data can be removed exactly.
"""

import asyncio
import logging
import math
import random
import time

import aiohttp

import store
from collector import Collector, MAX_SEGMENT_S, closest_on_segment

log = logging.getLogger("demo")

DEMO_PREFIX = "zz"
DAYS = 60
# Relative traffic in each hour of the day: quiet at night, busiest
# in the morning and early evening.
HOUR_WEIGHTS = [0.25, 0.1, 0.05, 0.05, 0.1, 0.5, 1.2, 1.5, 1.4, 1.3, 1.2, 1.2,
                1.2, 1.2, 1.2, 1.3, 1.4, 1.6, 1.6, 1.4, 1.2, 1.0, 0.7, 0.45]


def count(db):
    return db.execute("SELECT count(*) FROM passes WHERE hex LIKE ?", (DEMO_PREFIX + "%",)).fetchone()[0]


def remove(db):
    db.execute("DELETE FROM positions WHERE pass_id IN (SELECT id FROM passes WHERE hex LIKE ?)",
               (DEMO_PREFIX + "%",))
    n = db.execute("DELETE FROM passes WHERE hex LIKE ?", (DEMO_PREFIX + "%",)).rowcount
    db.commit()
    return n


async def fetch_history(base_url):
    """Read the receiver's history snapshots: about the last hour, every 30 s."""
    snapshots = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        for i in range(120):
            try:
                async with s.get(f"{base_url}/history_{i}.json") as resp:
                    if resp.status != 200:
                        break
                    snapshots.append(await resp.json(content_type=None))
            except Exception as err:
                log.warning("Cannot read history_%d.json: %s", i, err)
                break
    return sorted(snapshots, key=lambda d: d.get("now", 0))


def templates_from(db, home, capture_m, snapshots):
    """Return tracks as lists of (seconds from start, x, y, alt_ft), with callsigns."""
    mem = store.init(":memory:")
    c = Collector(mem, home, "", capture_m, poll_s=30)
    for snap in snapshots:
        c.ingest(snap)
    found = []
    for source in (mem, db):
        for pid, flight in source.execute(
                "SELECT id, flight FROM passes WHERE points >= 3 AND hex NOT LIKE ?", (DEMO_PREFIX + "%",)):
            pts = source.execute(
                "SELECT ts, lat_e5, lon_e5, alt_ft FROM positions WHERE pass_id = ? ORDER BY ts", (pid,)
            ).fetchall()
            t0 = pts[0][0]
            track = [(ts - t0, *home.xy(lat / 1e5, lon / 1e5), alt) for ts, lat, lon, alt in pts]
            found.append((flight, track))
    mem.close()
    return found


def generate(db_path, home, capture_m, templates, hourly_rate):
    db = store.connect(db_path)
    rng = random.Random(42)
    now = int(time.time())
    per_day = max(60, min(400, round(hourly_rate * sum(HOUR_WEIGHTS))))
    passes = 0
    for day in range(DAYS, -1, -1):
        midnight = time.mktime(time.localtime(now - day * 86400)[:3] + (0, 0, 0, 0, 0, -1))
        weekend = time.localtime(midnight).tm_wday >= 5
        n = round(per_day * (0.85 if weekend else 1.0) * rng.uniform(0.8, 1.2))
        for _ in range(n):
            hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
            t0 = int(midnight + hour * 3600 + rng.uniform(0, 3600))
            flight, track = rng.choice(templates)
            if t0 + track[-1][0] > now:
                continue
            if insert_clone(db, home, capture_m, rng, passes + 1, flight, track, t0):
                passes += 1
        db.commit()
    db.close()
    return passes


def insert_clone(db, home, capture_m, rng, n, flight, track, t0):
    # Shift the track sideways a little, and sometimes fly it the other way,
    # as when the airports change runway direction.
    reverse = rng.random() < 0.4
    pts = list(reversed(track)) if reverse else track
    end = track[-1][0]
    dx, dy = rng.gauss(0, 700), rng.gauss(0, 700)
    alt_scale = rng.uniform(0.9, 1.1)
    rows = []
    for t, x, y, alt in pts:
        x, y = x + dx, y + dy
        if math.hypot(x, y) > capture_m:
            continue
        ts = t0 + (end - t if reverse else t)
        a = None if alt is None else round(alt * alt_scale / 25) * 25
        rows.append((ts, x, y, a))
    if len(rows) < 2:
        return False

    min_d, min_ts, min_alt = math.hypot(rows[0][1], rows[0][2]), rows[0][0], rows[0][3]
    for (ta, xa, ya, aa), (tb, xb, yb, ab) in zip(rows, rows[1:]):
        t, d = closest_on_segment(xa, ya, xb, yb) if tb - ta <= MAX_SEGMENT_S else (1.0, math.hypot(xb, yb))
        if d < min_d:
            min_d, min_ts = d, round(ta + t * (tb - ta))
            min_alt = round(aa + t * (ab - aa)) if aa is not None and ab is not None else ab
    hex_ = f"{DEMO_PREFIX}{n:04x}"
    cur = db.execute(
        """INSERT INTO passes (hex, flight, category, start_ts, end_ts, min_ts, min_dist_m, min_alt_ft, points)
           VALUES (?, ?, 'demo', ?, ?, ?, ?, ?, ?)""",
        (hex_, flight, rows[0][0], rows[-1][0], min_ts, round(min_d), min_alt, len(rows)),
    )
    db.executemany(
        "INSERT OR IGNORE INTO positions VALUES (?, ?, ?, ?, ?)",
        [(cur.lastrowid, ts, round((home.lat + y / home.ky) * 1e5), round((home.lon + x / home.kx) * 1e5), a)
         for ts, x, y, a in rows],
    )
    return True


async def apply(enabled, db, db_path, home, base_url, capture_m):
    """Create the demo data if the option is on and none exists; remove it if off."""
    existing = count(db)
    if not enabled:
        if existing:
            log.info("Removed %d demo passes", remove(db))
        return
    if existing:
        log.info("%d demo passes already present", existing)
        return
    snapshots = await fetch_history(base_url)
    templates = templates_from(db, home, capture_m, snapshots)
    if not templates:
        log.warning("No tracks in the receiver history to build demo data from")
        return
    span_h = max(0.25, (snapshots[-1]["now"] - snapshots[0]["now"]) / 3600) if snapshots else 1
    hourly_rate = len(templates) / span_h
    log.info("Building %d days of demo data from %d real tracks", DAYS, len(templates))
    n = await asyncio.to_thread(generate, db_path, home, capture_m, templates, hourly_rate)
    log.info("Added %d demo passes", n)
