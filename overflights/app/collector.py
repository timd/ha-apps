"""Polls the receiver's aircraft.json and turns positions into passes."""

import asyncio
import logging
import math
import time

import aiohttp

log = logging.getLogger("collector")

# A gap longer than this starts a new pass for the same aircraft.
PASS_GAP_S = 600
# Positions further apart than this are not joined when the closest approach
# is computed, because the aircraft may have turned in between.
MAX_SEGMENT_S = 120


def altitude_ft(ac):
    alt = ac.get("alt_baro")
    if alt == "ground":
        return 0
    if isinstance(alt, (int, float)):
        return int(alt)
    alt = ac.get("alt_geom")
    return int(alt) if isinstance(alt, (int, float)) else None


def closest_on_segment(ax, ay, bx, by):
    """Return (t, distance) of the point on segment A-B nearest the origin."""
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
    return t, math.hypot(ax + t * dx, ay + t * dy)


class PassState:
    __slots__ = ("id", "last_ts", "last_x", "last_y", "last_alt",
                 "min_dist", "min_ts", "min_alt", "flight", "points")


class Collector:
    def __init__(self, db, home, source_url, capture_m, poll_s, airport=None, airport_m=0,
                 overhead_m=0, overhead_alt_ft=None):
        """`airport` is (lat, lon) or None. Positions within `airport_m` of it
        are kept too, so arrivals and departures reach the airport. Aircraft
        within `overhead_m` of the house, and below `overhead_alt_ft` if it is
        set, are overhead."""
        self.db = db
        self.home = home
        self.source_url = source_url
        self.capture_m = capture_m
        self.airport = home.xy(*airport) if airport and airport_m else None
        self.airport_m = airport_m
        self.poll_s = poll_s
        self.open = {}
        self.last_ok = None
        self.last_error = None
        self.aircraft_seen = 0
        self.overhead_m = overhead_m
        self.overhead_alt_ft = overhead_alt_ft or None
        self.overhead = []
        self._load_open()

    def _load_open(self):
        """Resume passes that were still open when the App stopped."""
        cutoff = int(time.time()) - PASS_GAP_S
        rows = self.db.execute(
            """SELECT p.id, p.hex, p.flight, p.min_ts, p.min_dist_m, p.min_alt_ft, p.points,
                      q.ts, q.lat_e5, q.lon_e5, q.alt_ft
               FROM passes p
               JOIN positions q ON q.pass_id = p.id AND q.ts = p.end_ts
               WHERE p.end_ts >= ?""",
            (cutoff,),
        ).fetchall()
        for (pid, hex_, flight, min_ts, min_dist, min_alt, points,
             ts, lat_e5, lon_e5, alt) in rows:
            st = PassState()
            st.id, st.flight, st.points = pid, flight, points
            st.min_ts, st.min_dist, st.min_alt = min_ts, min_dist, min_alt
            st.last_ts, st.last_alt = ts, alt
            st.last_x, st.last_y = self.home.xy(lat_e5 / 1e5, lon_e5 / 1e5)
            self.open[hex_] = st
        if rows:
            log.info("Resumed %d open passes", len(rows))

    def ingest(self, data):
        now = data.get("now") or time.time()
        positions = []
        updates = []
        overhead = []
        for ac in data.get("aircraft", []):
            lat, lon = ac.get("lat"), ac.get("lon")
            if lat is None or lon is None:
                continue
            seen_pos = ac.get("seen_pos", 0)
            if seen_pos > self.poll_s + 2:
                continue
            x, y = self.home.xy(lat, lon)
            dist = math.hypot(x, y)
            if dist > self.capture_m and not self._near_airport(x, y):
                continue

            hex_ = ac["hex"]
            ts = int(round(now - seen_pos))
            alt = altitude_ft(ac)
            flight = (ac.get("flight") or "").strip() or None
            if dist <= self.overhead_m and (self.overhead_alt_ft is None
                                            or (alt is not None and alt <= self.overhead_alt_ft)):
                overhead.append(self._overhead_entry(ac, hex_, flight, lat, lon, alt, dist))
            st = self.open.get(hex_)
            if st is not None and ts <= st.last_ts:
                continue

            if st is None or ts - st.last_ts > PASS_GAP_S:
                cur = self.db.execute(
                    """INSERT INTO passes (hex, flight, category, start_ts, end_ts,
                                           min_ts, min_dist_m, min_alt_ft, points)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (hex_, flight, ac.get("category"), ts, ts, ts, round(dist), alt),
                )
                st = PassState()
                st.id, st.flight, st.points = cur.lastrowid, flight, 0
                st.min_dist, st.min_ts, st.min_alt = dist, ts, alt
                self.open[hex_] = st
            else:
                if ts - st.last_ts <= MAX_SEGMENT_S:
                    t, d = closest_on_segment(st.last_x, st.last_y, x, y)
                else:
                    t, d = 1.0, dist
                if d < st.min_dist:
                    st.min_dist = d
                    st.min_ts = round(st.last_ts + t * (ts - st.last_ts))
                    if st.last_alt is not None and alt is not None:
                        st.min_alt = round(st.last_alt + t * (alt - st.last_alt))
                    else:
                        st.min_alt = alt if t > 0.5 else st.last_alt
                if flight and not st.flight:
                    st.flight = flight

            st.last_ts, st.last_x, st.last_y, st.last_alt = ts, x, y, alt
            st.points += 1
            positions.append((st.id, ts, round(lat * 1e5), round(lon * 1e5), alt))
            updates.append((st.flight, ts, st.min_ts, round(st.min_dist), st.min_alt,
                            st.points, st.id))

        if positions:
            self.db.executemany("INSERT OR IGNORE INTO positions VALUES (?, ?, ?, ?, ?)", positions)
            self.db.executemany(
                """UPDATE passes SET flight = ?, end_ts = ?, min_ts = ?, min_dist_m = ?,
                                     min_alt_ft = ?, points = ? WHERE id = ?""",
                updates,
            )
            self.db.commit()

        for hex_ in [h for h, st in self.open.items() if now - st.last_ts > PASS_GAP_S]:
            del self.open[hex_]
        for entry in overhead:
            st = self.open.get(entry["hex"])
            entry["pass_id"] = st.id if st else None
            entry["callsign"] = entry["callsign"] or (st.flight if st else None)
        self.overhead = sorted(overhead, key=lambda e: e["distance_m"])
        self.aircraft_seen = len(data.get("aircraft", []))

    @staticmethod
    def _overhead_entry(ac, hex_, flight, lat, lon, alt, dist):
        rate = ac.get("baro_rate", ac.get("geom_rate"))
        return {
            "hex": hex_, "callsign": flight, "lat": lat, "lon": lon, "altitude_ft": alt,
            "distance_m": round(dist),
            "speed_kt": round(ac["gs"]) if isinstance(ac.get("gs"), (int, float)) else None,
            "track": ac.get("track"),
            "vertical_fpm": rate if isinstance(rate, (int, float)) else None,
            "squawk": ac.get("squawk"), "category": ac.get("category"),
        }

    def _near_airport(self, x, y):
        return self.airport is not None and math.dist((x, y), self.airport) <= self.airport_m

    async def run(self):
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                started = time.monotonic()
                try:
                    async with session.get(self.source_url) as resp:
                        resp.raise_for_status()
                        data = await resp.json(content_type=None)
                    self.ingest(data)
                    if self.last_error:
                        log.info("Receiver reachable again")
                    self.last_ok, self.last_error = time.time(), None
                except Exception as err:  # keep polling whatever goes wrong
                    self.overhead = []
                    if str(err) != self.last_error:
                        log.warning("Poll failed: %s", err)
                    self.last_error = str(err)
                await asyncio.sleep(max(0.5, self.poll_s - (time.monotonic() - started)))
