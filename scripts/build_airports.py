#!/usr/bin/env python3
"""Build overflights/app/airports.json.gz from OurAirports (public domain).

Usage: scripts/build_airports.py [folder with airports.csv and runways.csv]

Without a folder, the script downloads the two files. The output holds large
and medium airports, and small airports with scheduled service, with their
runway ends:

    {"airports": {ident: [lat, lon, name, [[lat1, lon1, lat2, lon2], ...]]},
     "codes": {other code: ident}}

`codes` maps ICAO, GPS and IATA codes to the airport's ident.
"""

import csv
import gzip
import io
import json
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://davidmegginson.github.io/ourairports-data/"
OUT = Path(__file__).resolve().parent.parent / "overflights" / "app" / "airports.json.gz"


def read(folder, name):
    if folder:
        return (Path(folder) / name).read_text(encoding="utf-8")
    with urllib.request.urlopen(SOURCE + name, timeout=60) as resp:
        return resp.read().decode("utf-8")


def num(value):
    try:
        return round(float(value), 5)
    except ValueError:
        return None


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    airports, codes = {}, {}
    for row in csv.DictReader(io.StringIO(read(folder, "airports.csv"))):
        kind = row["type"]
        if kind not in ("large_airport", "medium_airport") and not (
                kind == "small_airport" and row["scheduled_service"] == "yes"):
            continue
        lat, lon = num(row["latitude_deg"]), num(row["longitude_deg"])
        if lat is None or lon is None:
            continue
        ident = row["ident"].upper()
        airports[ident] = [lat, lon, row["name"], []]
        for key in ("icao_code", "gps_code", "iata_code"):
            code = row[key].strip().upper()
            if code and code != ident:
                codes.setdefault(code, ident)

    for row in csv.DictReader(io.StringIO(read(folder, "runways.csv"))):
        airport = airports.get(row["airport_ident"].upper())
        if airport is None or row["closed"] == "1":
            continue
        ends = [num(row[k]) for k in ("le_latitude_deg", "le_longitude_deg",
                                      "he_latitude_deg", "he_longitude_deg")]
        if None not in ends:
            airport[3].append(ends)

    # Codes that are also some airport's ident would be ambiguous.
    codes = {c: i for c, i in codes.items() if c not in airports}
    data = json.dumps({"airports": airports, "codes": codes}, separators=(",", ":"))
    OUT.write_bytes(gzip.compress(data.encode("utf-8"), mtime=0))
    with_runways = sum(1 for a in airports.values() if a[3])
    print(f"{len(airports)} airports, {with_runways} with runway ends, "
          f"{len(codes)} other codes: {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
