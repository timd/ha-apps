"""Aircraft and route details from adsbdb.com, kept in the database.

The receiver sends only an aircraft's address and callsign. adsbdb.com gives
the registration, type and owner for the address, and the airline and route
for the callsign. The App asks only about aircraft overhead, and asks about
each one once: aircraft details are kept for 30 days and routes for a day.
"""

import asyncio
import json
import logging
import math
import time

import aiohttp

log = logging.getLogger("lookup")

API = "https://api.adsbdb.com/v0"
USER_AGENT = "Overflights/1 (Home Assistant App; +https://github.com/timd/ha-apps)"
AIRCRAFT_AGE_S = 30 * 86400
ROUTE_AGE_S = 86400
# After a failed request, wait this long before asking about the same key.
RETRY_S = 300
# A route is plausible if the flight from origin to destination through the
# aircraft's position is at most this much longer than the direct flight.
MAX_DETOUR = 1.25
# Positions this close to an end of the route always fit it, whatever the
# detour, because an aircraft may circle near an airport.
NEAR_END_M = 60000

SCHEMA = """
CREATE TABLE IF NOT EXISTS lookups (
  key TEXT PRIMARY KEY,   -- "aircraft:<hex>" or "route:<callsign>"
  ts INTEGER NOT NULL,
  data TEXT               -- JSON, or NULL if adsbdb does not know the key
);
"""


def aircraft_details(r):
    a = r["aircraft"]
    return {
        "registration": a.get("registration"),
        "type": " ".join(v for v in (a.get("manufacturer"), a.get("type")) if v) or None,
        "icao_type": a.get("icao_type"),
        "owner": a.get("registered_owner"),
        "country": a.get("registered_owner_country_name"),
        "photo": a.get("url_photo_thumbnail") or a.get("url_photo"),
    }


def route_details(r):
    f = r["flightroute"]

    def airport(a):
        return {"code": a.get("iata_code") or a.get("icao_code"), "name": a.get("name"),
                "city": a.get("municipality"), "lat": a.get("latitude"), "lon": a.get("longitude")}

    return {"airline": (f.get("airline") or {}).get("name"),
            "origin": airport(f["origin"]), "destination": airport(f["destination"])}


def great_circle_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def plausible(route, lat, lon):
    """False if the aircraft is far off the line from origin to destination.

    adsbdb takes routes from schedules, and a callsign can move to another
    route, so its answer is sometimes years out of date.
    """
    o, d = route["origin"], route["destination"]
    if None in (o["lat"], o["lon"], d["lat"], d["lon"]):
        return True
    to_o = great_circle_m(lat, lon, o["lat"], o["lon"])
    to_d = great_circle_m(lat, lon, d["lat"], d["lon"])
    if min(to_o, to_d) <= NEAR_END_M:
        return True
    return to_o + to_d <= MAX_DETOUR * great_circle_m(o["lat"], o["lon"], d["lat"], d["lon"])


class Lookup:
    def __init__(self, db):
        self.db = db
        db.executescript(SCHEMA)
        db.commit()
        self.cache = {}     # key -> (ts, data)
        self.pending = set()
        self.failed = {}    # key -> time of the last failure
        self.session = None

    async def close(self):
        if self.session:
            await self.session.close()

    def details(self, hex_, callsign, lat, lon):
        """Return what is known now, and start a lookup of anything missing."""
        out = {}
        # A "~" address is not an ICAO address, so adsbdb cannot know it.
        aircraft = None if hex_.startswith("~") else self._get(f"aircraft:{hex_}", AIRCRAFT_AGE_S)
        if aircraft:
            out.update(aircraft)
        if callsign:
            route = self._get(f"route:{callsign}", ROUTE_AGE_S)
            if route:
                out.update(route, route_plausible=plausible(route, lat, lon))
        return out

    def _get(self, key, max_age):
        if key not in self.cache:
            row = self.db.execute("SELECT ts, data FROM lookups WHERE key = ?", (key,)).fetchone()
            if row:
                self.cache[key] = (row[0], json.loads(row[1]) if row[1] else None)
        ts, data = self.cache.get(key, (0, None))
        if time.time() - ts > max_age and key not in self.pending \
                and time.time() - self.failed.get(key, 0) > RETRY_S:
            self.pending.add(key)
            asyncio.ensure_future(self._fetch(key))
        return data

    async def _fetch(self, key):
        kind, value = key.split(":", 1)
        path = f"aircraft/{value}" if kind == "aircraft" else f"callsign/{value}"
        if self.session is None:
            self.session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                                                 timeout=aiohttp.ClientTimeout(total=15))
        try:
            async with self.session.get(f"{API}/{path}") as r:
                if r.status == 404:
                    data = None  # adsbdb does not know it
                elif r.status == 200:
                    body = (await r.json(content_type=None))["response"]
                    data = aircraft_details(body) if kind == "aircraft" else route_details(body)
                else:
                    raise aiohttp.ClientResponseError(r.request_info, (), status=r.status)
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError, ValueError) as e:
            log.warning("Cannot look up %s at adsbdb.com: %s", key, e or type(e).__name__)
            self.failed[key] = time.time()
            return
        finally:
            self.pending.discard(key)
        now = int(time.time())
        self.cache[key] = (now, data)
        self.db.execute("INSERT OR REPLACE INTO lookups VALUES (?, ?, ?)",
                        (key, now, json.dumps(data) if data else None))
        self.db.commit()

    def prune(self):
        """Delete entries too old to use. Returns the count."""
        n = self.db.execute("DELETE FROM lookups WHERE ts < ?",
                            (int(time.time()) - AIRCRAFT_AGE_S,)).rowcount
        self.db.commit()
        self.cache.clear()
        return n
