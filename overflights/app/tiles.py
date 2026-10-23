"""Map tiles, fetched once from the tile server and kept on disk.

Public tile servers such as OpenStreetMap's ask each application to identify
itself, to cache tiles, and to use few connections. The page asks the App for
its tiles, so each tile leaves the tile server once a month at most, however
often the page is opened.
"""

import asyncio
import logging
import time
from pathlib import Path

import aiohttp
from aiohttp import web

log = logging.getLogger("overflights")

USER_AGENT = "Overflights/1 (Home Assistant App; +https://github.com/timd/ha-apps)"
MAX_ZOOM = 19
# Tiles older than this are fetched again, or deleted by prune().
MAX_AGE_S = 30 * 86400
# A browser keeps a tile this long before it asks the App again.
BROWSER_AGE_S = 7 * 86400


class TileCache:
    def __init__(self, folder, url):
        self.folder = Path(folder)
        self.url = url
        # OpenStreetMap's tile policy allows at most two connections.
        self.limit = asyncio.Semaphore(2)
        self.pending = {}
        self.session = None
        self.warned = False

    async def close(self):
        if self.session:
            await self.session.close()

    async def handle(self, request):
        try:
            z, x, y = (int(request.match_info[k]) for k in ("z", "x", "y"))
        except ValueError:
            raise web.HTTPNotFound()
        if not (0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z):
            raise web.HTTPNotFound()
        path = self.folder / str(z) / str(x) / f"{y}.png"
        fresh = path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_S
        if not fresh:
            # Several requests for one tile share one fetch.
            key = (z, x, y)
            if key not in self.pending:
                self.pending[key] = asyncio.ensure_future(self.fetch(z, x, y, path))
            try:
                body = await asyncio.shield(self.pending[key])
            finally:
                self.pending.pop(key, None)
            if body is not None:
                # The tile server refused the tile. Pass on its image, but
                # neither the App nor the browser keeps it.
                return web.Response(body=body, content_type="image/png",
                                    headers={"Cache-Control": "no-store"})
            if not path.exists():
                raise web.HTTPBadGateway(text="The tile server did not answer.")
        return web.FileResponse(path, headers={"Cache-Control": f"max-age={BROWSER_AGE_S}"})

    async def fetch(self, z, x, y, path):
        """Store the tile at path. Returns the body only for a refused tile.

        If the tile server fails, an old copy stays in place and is served.
        """
        if self.session is None:
            self.session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                                                 timeout=aiohttp.ClientTimeout(total=20))
        url = self.url.format(z=z, x=x, y=y, s="a")
        try:
            async with self.limit, self.session.get(url) as r:
                body = await r.read()
                # OpenStreetMap answers a blocked client with status 200 and
                # an "Access blocked" image, marked by this header.
                if r.status != 200 or "x-blocked" in r.headers:
                    if not self.warned:
                        log.warning("The tile server refused %s (HTTP %d%s). See the "
                                    "tile_url option.", url, r.status,
                                    ", blocked" if "x-blocked" in r.headers else "")
                        self.warned = True
                    return body if r.status == 200 else None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("Cannot fetch map tile %s: %s", url, e)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return None

    def prune(self):
        """Delete tiles older than MAX_AGE_S, which the App would fetch again
        anyway. Returns the count."""
        cutoff = time.time() - MAX_AGE_S
        n = 0
        for f in self.folder.rglob("*.png"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        return n
