"""Overflights: log aircraft that pass near the house and chart them."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import aiohttp
from aiohttp import web

import demo
import store
from sensors import Sensors
from collector import Collector

log = logging.getLogger("overflights")

DATA_DIR = Path(os.environ.get("OVERFLIGHTS_DATA", "/data"))
OPTIONS = Path(os.environ.get("OVERFLIGHTS_OPTIONS", DATA_DIR / "options.json"))
STATIC = Path(__file__).parent / "static"
PORT = int(os.environ.get("OVERFLIGHTS_PORT", "8099"))
# The page asks for at most this many tracks, newest first.
MAX_TRACKS = 20000


async def receiver_position(base_url):
    url = base_url.rstrip("/") + "/receiver.json"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        while True:
            try:
                async with s.get(url) as resp:
                    data = await resp.json(content_type=None)
                return data["lat"], data["lon"]
            except Exception as err:
                log.warning("Cannot read the receiver position from %s: %s", url, err)
                await asyncio.sleep(30)


def query_args(request):
    q = request.query
    args = {
        "since": int(q.get("since", 0)),
        "until": int(q.get("until", 2**31)),
        "max_alt": int(q["max_alt"]) if q.get("max_alt") else None,
        "radius": int(q["radius"]) if q.get("radius") else None,
    }
    where = ["min_ts >= :since", "min_ts < :until"]
    if args["max_alt"] is not None:
        where.append("min_alt_ft <= :max_alt")
    if args["radius"] is not None:
        where.append("min_dist_m <= :radius")
    return " AND ".join(where), args


def read_passes(db_path, where, args):
    db = store.connect(db_path)
    try:
        return db.execute(
            f"""SELECT id, min_ts, min_dist_m, min_alt_ft, flight, hex
                FROM passes WHERE {where} ORDER BY min_ts""",
            args,
        ).fetchall()
    finally:
        db.close()


def read_tracks(db_path, where, args):
    """Return each track as one flat list: first point, then deltas (1e-5 deg)."""
    db = store.connect(db_path)
    try:
        rows = db.execute(
            f"""SELECT pass_id, lat_e5, lon_e5 FROM positions
                WHERE pass_id IN (SELECT id FROM passes WHERE {where}
                                  ORDER BY min_ts DESC LIMIT {MAX_TRACKS})
                ORDER BY pass_id, ts""",
            args,
        )
        tracks, current, coords, plat, plon = [], None, None, 0, 0
        for pid, lat, lon in rows:
            if pid != current:
                current, coords, plat, plon = pid, [], 0, 0
                tracks.append([pid, coords])
            coords += (lat - plat, lon - plon)
            plat, plon = lat, lon
        return tracks
    finally:
        db.close()


def make_app(state):
    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(_request):
        return web.FileResponse(STATIC / "index.html")

    @routes.get("/api/info")
    async def info(_request):
        db = store.connect(state["db_path"])
        try:
            count, first = db.execute("SELECT count(*), min(start_ts) FROM passes").fetchone()
            demo_count = demo.count(db)
        finally:
            db.close()
        c = state["collector"]
        opts = state["options"]
        return web.json_response({
            "home": [state["home"].lat, state["home"].lon],
            "capture_radius_m": round(opts["capture_radius_km"] * 1000),
            "default_radius_m": round(opts["default_radius_km"] * 1000),
            "default_max_alt_ft": opts.get("default_max_altitude_ft") or None,
            "passes": count,
            "demo_passes": demo_count,
            "first_ts": first,
            "last_poll_ok": c.last_ok,
            "last_error": c.last_error,
            "aircraft_now": c.aircraft_seen,
            "db_bytes": sum(p.stat().st_size for p in DATA_DIR.glob("overflights.db*")),
            "now": time.time(),
        })

    @routes.get("/api/passes")
    async def passes(request):
        where, args = query_args(request)
        rows = await asyncio.to_thread(read_passes, state["db_path"], where, args)
        return web.json_response({"fields": ["id", "ts", "dist_m", "alt_ft", "flight", "hex"],
                                  "rows": rows})

    @routes.get("/api/tracks")
    async def tracks(request):
        where, args = query_args(request)
        rows = await asyncio.to_thread(read_tracks, state["db_path"], where, args)
        return web.json_response({"limit": MAX_TRACKS, "tracks": rows})

    @routes.get("/api/health")
    async def health(_request):
        ok = state["collector"].last_ok and time.time() - state["collector"].last_ok < 120
        return web.Response(status=200 if ok else 503, text="ok" if ok else "stale")

    app = web.Application()
    app.add_routes(routes)
    app.router.add_static("/static/", STATIC)
    return app


async def prune_loop(db, days):
    while True:
        n = store.prune(db, int(time.time()) - days * 86400)
        if n:
            log.info("Deleted %d passes older than %d days", n, days)
        await asyncio.sleep(3600)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    opts = json.loads(OPTIONS.read_text())
    base = opts["receiver_url"].rstrip("/")

    if opts.get("latitude") is not None and opts.get("longitude") is not None:
        lat, lon = opts["latitude"], opts["longitude"]
    else:
        lat, lon = await receiver_position(base)
    home = store.Home(lat, lon)

    db_path = DATA_DIR / "overflights.db"
    db = store.init(db_path)
    old = store.get_meta(db, "home")
    if old and old != f"{lat},{lon}":
        log.warning("Home moved from %s to %s,%s: distances of older passes use the old home",
                    old, lat, lon)
    store.set_meta(db, "home", f"{lat},{lon}")
    log.info("Home %.5f,%.5f, capture radius %.1f km, time zone %s", lat, lon,
             opts["capture_radius_km"], time.strftime("%Z"))

    collector = Collector(db, home, base + "/aircraft.json",
                          opts["capture_radius_km"] * 1000, opts["poll_seconds"])
    state = {"db_path": db_path, "home": home, "collector": collector, "options": opts}

    runner = web.AppRunner(make_app(state), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Serving on port %d", PORT)

    demo_db = store.connect(db_path)
    await demo.apply(opts.get("demo_data", False), demo_db, db_path, home, base,
                     opts["capture_radius_km"] * 1000)
    demo_db.close()
    sensors = Sensors(db_path, collector, opts["default_radius_km"] * 1000,
                      opts.get("default_max_altitude_ft"))
    await asyncio.gather(collector.run(), prune_loop(db, opts["retention_days"]), sensors.run())


if __name__ == "__main__":
    asyncio.run(main())
