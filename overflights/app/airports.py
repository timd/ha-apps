"""Look up an airport and its runway ends by code, offline.

The data comes from OurAirports (public domain), converted by
scripts/build_airports.py.
"""

import gzip
import json
from pathlib import Path

DATA = Path(__file__).parent / "airports.json.gz"


def lookup(code):
    """Return (ident, name, [lat, lon], runways) for an ICAO or IATA code, or None.

    Each runway is [lat1, lon1, lat2, lon2], its two ends.
    """
    data = json.loads(gzip.decompress(DATA.read_bytes()))
    code = code.strip().upper()
    ident = code if code in data["airports"] else data["codes"].get(code)
    if ident is None:
        return None
    lat, lon, name, runways = data["airports"][ident]
    return ident, name, [lat, lon], runways
