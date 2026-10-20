"""Sort passes into arrivals, departures and transits from their altitude profile.

A pass that descends is an arrival and one that climbs is a departure, if it
is low enough at its closest point to the house. Everything else is a
transit. If the options give an airport, an arrival must also end closer to
it than it started, and a departure further away; this keeps out aircraft
that start their descent toward an airport somewhere else.
"""

import math

ARRIVAL = "arrival"
DEPARTURE = "departure"
TRANSIT = "transit"
UNKNOWN = "unknown"
KINDS = (ARRIVAL, DEPARTURE, TRANSIT, UNKNOWN)

# Smaller altitude changes are level flight with noise.
MIN_CHANGE_FT = 1000
# Highest altitude at the closest point for each class. Departures climb
# faster than arrivals descend, so they are higher at the same distance.
ARRIVAL_MAX_FT = 20000
DEPARTURE_MAX_FT = 25000
# Smaller changes in distance to the airport do not show a direction.
MIN_AIRPORT_CHANGE_M = 2000
MIN_POINTS = 3

# Columns that classify() needs, from passes p and the first (a) and last (b)
# position of each pass.
COLUMNS = "p.points, p.min_alt_ft, a.alt_ft, a.lat_e5, a.lon_e5, b.alt_ft, b.lat_e5, b.lon_e5"
JOINS = """LEFT JOIN positions a ON a.pass_id = p.id AND a.ts = p.start_ts
           LEFT JOIN positions b ON b.pass_id = p.id AND b.ts = p.end_ts"""


class Classifier:
    def __init__(self, home, airport=None):
        """`airport` is (lat, lon) or None."""
        self.home = home
        self.airport = home.xy(*airport) if airport else None

    def __call__(self, points, min_alt, alt0, lat0, lon0, alt1, lat1, lon1):
        if points < MIN_POINTS or alt0 is None or alt1 is None or min_alt is None:
            return UNKNOWN
        change = alt1 - alt0
        if change <= -MIN_CHANGE_FT and min_alt <= ARRIVAL_MAX_FT and self._toward(lat0, lon0, lat1, lon1, 1):
            return ARRIVAL
        if change >= MIN_CHANGE_FT and min_alt <= DEPARTURE_MAX_FT and self._toward(lat0, lon0, lat1, lon1, -1):
            return DEPARTURE
        return TRANSIT

    def _toward(self, lat0, lon0, lat1, lon1, sign):
        """True if the pass moves toward the airport (sign 1) or away from it (-1)."""
        if self.airport is None:
            return True
        d0 = math.dist(self.home.xy(lat0 / 1e5, lon0 / 1e5), self.airport)
        d1 = math.dist(self.home.xy(lat1 / 1e5, lon1 / 1e5), self.airport)
        return sign * (d0 - d1) >= MIN_AIRPORT_CHANGE_M
