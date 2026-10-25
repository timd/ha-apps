"""Overflights: log aircraft that pass near the house and chart them."""

import asyncio
import hashlib
import json
import logging
import os
import signal
import time
from pathlib import Path

import aiohttp
from aiohttp import web

import airports
import demo
import store
import tiles
from lookup import Lookup
from classify import COLUMNS, JOINS, KINDS, Classifier
from sensors import Sensors
from collector import PASS_GAP_S, Collector

log = logging.getLogger("overflights")

DATA_DIR = Path(os.environ.get("OVERFLIGHTS_DATA", "/data"))
OPTIONS = Path(os.environ.get("OVERFLIGHTS_OPTIONS", DATA_DIR / "options.json"))
STATIC = Path(__file__).parent / "static"
PORT = int(os.environ.get("OVERFLIGHTS_PORT", "8099"))
DEFAULT_TILE_URL = "https://tile.openstreetmap.de/{z}/{x}/{y}.png"
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


def query_args(request, capture_m):
    """Passes that match the page's filters. A pass that only crossed the
    airport area, and never came within `capture_m` of the house, never matches."""
    q = request.query
    args = {
        "capture": capture_m,
        "since": int(q.get("since", 0)),
        "until": int(q.get("until", 2**31)),
        "max_alt": int(q["max_alt"]) if q.get("max_alt") else None,
        "radius": int(q["radius"]) if q.get("radius") else None,
    }
    where = ["p.min_ts >= :since", "p.min_ts < :until", "p.min_dist_m <= :capture"]
    if args["max_alt"] is not None:
        where.append("p.min_alt_ft <= :max_alt")
    if args["radius"] is not None:
        where.append("p.min_dist_m <= :radius")
    kinds = set(q["kind"].split(",")) & set(KINDS) if q.get("kind") else None
    return " AND ".join(where), args, kinds


def classified(db, classify, where, args, kinds, order="ASC"):
    """Yield (row..., kind) for each pass that matches, with `kind` last."""
    rows = db.execute(
        f"""SELECT p.id, p.min_ts, p.min_dist_m, p.min_alt_ft, p.flight, p.hex, {COLUMNS}
            FROM passes p {JOINS} WHERE {where} ORDER BY p.min_ts {order}""",
        args,
    )
    for row in rows:
        kind = classify(*row[6:])
        if kinds is None or kind in kinds:
            yield (*row[:6], kind)


def read_passes(db_path, classify, where, args, kinds):
    db = store.connect(db_path)
    try:
        return list(classified(db, classify, where, args, kinds))
    finally:
        db.close()


def read_tracks(db_path, classify, where, args, kinds):
    """Return each track as [id, kind, ts, coords]: `ts` is the time of the
    closest point, and `coords` the first point, then deltas (1e-5 deg)."""
    db = store.connect(db_path)
    try:
        kind_of = {}
        for row in classified(db, classify, where, args, kinds, order="DESC"):
            kind_of[row[0]] = (row[6], row[1])
            if len(kind_of) >= MAX_TRACKS:
                break
        rows = db.execute(
            """SELECT pass_id, lat_e5, lon_e5 FROM positions
               WHERE pass_id IN (SELECT value FROM json_each(?))
               ORDER BY pass_id, ts""",
            (json.dumps(list(kind_of)),),
        )
        tracks, current, coords, plat, plon = [], None, None, 0, 0
        for pid, lat, lon in rows:
            if pid != current:
                current, coords, plat, plon = pid, [], 0, 0
                tracks.append([pid, *kind_of[pid], coords])
            coords += (lat - plat, lon - plon)
            plat, plon = lat, lon
        return tracks
    finally:
        db.close()


def overhead_now(state):
    """The aircraft overhead now, nearest first, with what adsbdb knows of them."""
    out = []
    for entry in state["collector"].overhead:
        entry = dict(entry)
        if state["lookup"]:
            entry.update(state["lookup"].details(entry["hex"], entry["callsign"], entry["lat"], entry["lon"]))
        out.append(entry)
    return out


def parse_runways(entries):
    """Read each runway as "lat,lon,lat,lon", the two ends. Skip bad entries."""
    runways = []
    for entry in entries or []:
        try:
            ends = [float(v) for v in entry.split(",")]
        except ValueError:
            ends = []
        if len(ends) == 4:
            runways.append(ends)
        else:
            log.warning("Ignoring runway %r: give it as lat,lon,lat,lon", entry)
    return runways


def make_app(state):
    routes = web.RouteTableDef()

    # The page names its scripts and stylesheets with a hash of all static
    # files, so a browser fetches new copies after any update.
    stamp = hashlib.sha1(b"".join(f.read_bytes() for f in sorted(STATIC.rglob("*")) if f.is_file())).hexdigest()[:10]
    page = (STATIC / "index.html").read_text().replace(".js\"", f".js?v={stamp}\"").replace(
        ".css\"", f".css?v={stamp}\"")

    @routes.get("/")
    async def index(_request):
        return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-cache"})

    @routes.get("/api/info")
    async def info(_request):
        db = store.connect(state["db_path"])
        try:
            count, first = db.execute("SELECT count(*), min(start_ts) FROM passes WHERE min_dist_m <= ?",
                                      (state["capture_m"],)).fetchone()
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
            "airport": state["airport"],
            "airport_radius_m": state["airport_m"] if state["airport"] else None,
            "runways": state["runways"],
            "passes": count,
            "demo_passes": demo_count,
            "first_ts": first,
            "last_poll_ok": c.last_ok,
            "last_error": c.last_error,
            "aircraft_now": c.aircraft_seen,
            "db_bytes": sum(p.stat().st_size for p in DATA_DIR.glob("overflights.db*")),
            "now": time.time(),
        })

    @routes.get("/api/now")
    async def now(_request):
        c = state["collector"]
        return web.json_response({
            "radius_m": c.overhead_m,
            "max_alt_ft": c.overhead_alt_ft,
            "lookup": state["lookup"] is not None,
            "receiving": c.last_error is None and c.last_ok is not None,
            "aircraft": overhead_now(state),
            "now": time.time(),
        })

    @routes.get("/api/passes")
    async def passes(request):
        rows = await asyncio.to_thread(read_passes, state["db_path"], state["classify"],
                                       *query_args(request, state["capture_m"]))
        return web.json_response({"fields": ["id", "ts", "dist_m", "alt_ft", "flight", "hex", "kind"],
                                  "rows": rows})

    @routes.get("/api/tracks")
    async def tracks(request):
        rows = await asyncio.to_thread(read_tracks, state["db_path"], state["classify"],
                                       *query_args(request, state["capture_m"]))
        return web.json_response({"limit": MAX_TRACKS, "tracks": rows})

    @routes.get("/api/health")
    async def health(_request):
        ok = state["collector"].last_ok and time.time() - state["collector"].last_ok < 120
        return web.Response(status=200 if ok else 503, text="ok" if ok else "stale")

    app = web.Application()
    app.add_routes(routes)
    app.router.add_get("/tiles/{z}/{x}/{y}.png", state["tiles"].handle)
    app.router.add_static("/static/", STATIC)
    return app


async def prune_loop(db, days, capture_m, tile_cache, lookup):
    while True:
        n = await asyncio.to_thread(tile_cache.prune)
        if n:
            log.info("Deleted %d old map tiles", n)
        if lookup:
            lookup.prune()
        n = store.prune(db, int(time.time()) - days * 86400)
        if n:
            log.info("Deleted %d passes older than %d days", n, days)
        n = store.prune_outside(db, capture_m, int(time.time()) - 2 * PASS_GAP_S)
        if n:
            log.info("Deleted %d passes that only crossed the airport area", n)
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

    capture_m = opts["capture_radius_km"] * 1000
    airport, runways = None, []
    if opts.get("airport"):
        found = airports.lookup(opts["airport"])
        if found:
            ident, name, airport, runways = found
            log.info("Airport %s, %s: %d runways with known ends", ident, name, len(runways))
        else:
            log.warning("Unknown airport code %r. Give an ICAO code such as EDDB, or an IATA "
                        "code such as BER", opts["airport"])
    # Explicit options override the lookup.
    if opts.get("airport_latitude") is not None and opts.get("airport_longitude") is not None:
        airport = [opts["airport_latitude"], opts["airport_longitude"]]
    if opts.get("runways"):
        runways = parse_runways(opts["runways"])
    if airport:
        log.info("Arrivals and departures are checked against the airport at %.4f,%.4f", *airport)
    airport_m = opts.get("airport_radius_km", 25) * 1000
    overhead_m = min(opts["default_radius_km"] * 1000, capture_m)
    collector = Collector(db, home, base + "/aircraft.json", capture_m, opts["poll_seconds"],
                          airport, airport_m, overhead_m, opts.get("default_max_altitude_ft"))
    lookup = Lookup(db) if opts.get("online_lookup", True) else None
    state = {"db_path": db_path, "home": home, "collector": collector, "options": opts, "lookup": lookup,
             "capture_m": capture_m, "airport": airport, "airport_m": airport_m,
             "runways": runways, "classify": Classifier(home, airport),
             "tiles": tiles.TileCache(DATA_DIR / "tiles", opts.get("tile_url") or DEFAULT_TILE_URL)}

    runner = web.AppRunner(make_app(state), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Serving on port %d", PORT)

    demo_db = store.connect(db_path)
    await demo.apply(opts.get("demo_data", False), demo_db, db_path, home, base,
                     opts["capture_radius_km"] * 1000)
    demo_db.close()
    sensors = Sensors(db_path, collector, state["classify"], overhead_m,
                      opts.get("default_max_altitude_ft"), lambda: overhead_now(state))
    # The App runs as PID 1, which ignores SIGTERM unless it handles it. Without
    # this, the Supervisor waits 10 seconds at each stop and then kills the App.
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    work = asyncio.gather(collector.run(), prune_loop(db, opts["retention_days"], capture_m, state["tiles"], lookup), sensors.run())
    stopped = asyncio.ensure_future(stop.wait())
    await asyncio.wait([work, stopped], return_when=asyncio.FIRST_COMPLETED)
    if work.done():
        work.result()  # raise whatever ended the work
    log.info("Stopping")
    work.cancel()
    await asyncio.gather(work, return_exceptions=True)
    await runner.cleanup()
    await state["tiles"].close()
    if lookup:
        await lookup.close()
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
