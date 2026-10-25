# Overflights

Overflights logs every aircraft that the ADS-B receiver sees within the capture
radius of the house. Open it from the Overflights item in the sidebar.

## How it works

Every few seconds the App reads `aircraft.json` from the ADS-B receiver. It
keeps each aircraft's positions inside the capture radius and groups them into
passes. A pass ends when an aircraft is not seen for 10 minutes. For each pass,
the App records the closest approach to the house. It takes that point from the
straight line between two consecutive positions, so it does not depend on the
moment a position was sampled.

## Arrivals, departures and transits

The App sorts each pass by how its altitude changes between its first and last
position in the capture area:

| Class | Rule |
| --- | --- |
| Arrival | Descends by 1,000 ft or more, and is at or below 20,000 ft at its closest point. |
| Departure | Climbs by 1,000 ft or more, and is at or below 25,000 ft at its closest point. |
| Transit | Every other pass: level, or too high to be landing or just departed. |
| Unclassified | Fewer than 3 positions, or no altitude. |

If you set an airport, an arrival must also end
at least 2 km closer to that airport than it started, and a departure 2 km
further away. A pass that fails this check is a transit. Without an airport, the
App counts every low descent as an arrival, for any airfield.

The map draws transits first, then arrivals, then departures on top. Tracks
fade with age: full strength for the last day, medium for the last week, and
faint for older ones. On the map, click a class in the legend to hide or show
its paths. The browser remembers the choice. The Type filter above the charts
limits the whole page to one class.

## Paths to the airport

With an airport set, the App also stores positions within
`airport_radius_km` (25 km) of the airport, for aircraft that also come within
the capture radius of the house. Arrivals and departures then continue on the
map toward the airport, until the receiver loses sight of them. An aircraft
that only crosses the airport area is not a pass, and the App deletes it.

A receiver some distance away cannot see aircraft low over the airport. Near
the ground, arrivals and departures disappear several kilometres from the
runway. If the App knows the runways, the map joins each arrival's last
position, and each departure's first, to a runway end with a dashed line.
The App joins only an aircraft within 25° of a runway's extended centreline,
and picks the nearest centreline. An aircraft that the receiver lost on a
downwind or base leg still has a turn to fly, so its path stays open.
The dashed line is an estimate, not a received path. Without runways, the
line goes to the airport position.

## Setting the airport

Enter the airport's ICAO code (for example `EDDB`) or IATA code (`BER`) in
**Airport** on the Configuration tab. The App looks up the airport position
and its runway ends in a copy of the [OurAirports](https://ourairports.com/)
database that it carries, so it needs no internet connection. The App log
names the airport it found and the number of runways. The copy holds large
and medium airports, and small airports with scheduled flights.

To override the lookup, or for an airfield that it does not know, set
`airport_latitude` and `airport_longitude`, and list the runways in
`runways`. Give each runway as its two ends, `lat,lon,lat,lon`:

```yaml
runways:
  - 52.36672,13.48093,52.37841,13.53021
  - 52.34544,13.46843,52.35843,13.52318
```

The App classifies passes when the page asks for them, so a change to these
options also applies to the passes that are already stored.

The Latest overflights table has its own period: the last hour, day or
week, or all time. It also uses the page's radius, altitude and type filters.

The page filters by radius and by altitude at the closest point. The radius
is only a view filter, so you can change it at any time without losing data.

## Options

| Option | Meaning |
| --- | --- |
| `receiver_url` | The receiver's data folder, which holds `aircraft.json` and `receiver.json`. |
| `latitude`, `longitude` | The house position. If empty, the App reads it from `receiver.json`. |
| `airport` | Optional. The ICAO or IATA code of the main airport near the house. The App looks up its position and runways. |
| `airport_latitude`, `airport_longitude` | Optional. Override the airport position from the code. |
| `airport_radius_km` | Positions within this distance of the airport are stored too. 0 turns this off. |
| `runways` | Optional. Override the runways from the code. Each runway's two ends as `lat,lon,lat,lon`. |
| `capture_radius_km` | Positions further away are not stored, except near the airport. Only aircraft that come this close are passes. |
| `poll_seconds` | How often the App reads the receiver. |
| `retention_days` | Passes older than this are deleted. |
| `default_radius_km` | The radius for the Today and Last sensors, and the page's radius until someone moves the slider. |
| `default_max_altitude_ft` | The altitude limit for the page and the sensors. 0 means any altitude. |
| `online_lookup` | Look up the registration, type, operator and route of each aircraft overhead at adsbdb.com. |
| `demo_data` | Adds 60 days of demo passes, made from the receiver's last hour of real tracks. Turn it off to delete them. |
| `tile_url` | Optional. The map's tile server, with `{z}`, `{x}` and `{y}`. Empty means `https://tile.openstreetmap.de/{z}/{x}/{y}.png`. |

## Overhead now

The card at the top of the page lists the aircraft that are overhead now,
nearest first: those within the page's radius of the house, and below
`default_max_altitude_ft`. `sensor.overflights_overhead` uses the same
radius.

When nothing is within the radius, the card's title changes to **Last
overhead**, and it shows the latest aircraft whose closest point came within
the radius: the time, the distance and altitude at the closest point, the
class, and the same details from adsbdb. The map marks that closest point
with a ring.

The radius slider is shared. The App keeps its value, so every browser opens
with it, and an open page follows a change made in another browser. Moving
the slider also changes the Overhead sensor. Until someone moves the slider,
the radius is `default_radius_km`. The
map marks each one with its callsign. The card updates every 5 seconds.

The receiver gives only the aircraft's address, callsign, position, altitude
and speed. If `online_lookup` is on, the App asks
[adsbdb.com](https://www.adsbdb.com/) for the registration, type, owner and
photo of each aircraft, and for the airline and route of each callsign. It
asks once for each aircraft (kept for 30 days) and each callsign (kept for a
day), and only about aircraft overhead. The first time, the details appear a
few seconds after the aircraft.

adsbdb takes routes from schedules, so a route can be years out of date. If
the aircraft is far off the line from origin to destination, the card says
so. Aircraft that send no position, such as many light aircraft, never show.

## Map tiles

The page gets its map tiles from the App, not from the tile server. The App
fetches each tile once, keeps it in `/data/tiles` for 30 days, and names
itself to the tile server. This follows the [OpenStreetMap tile
policy](https://operations.osmfoundation.org/policies/tiles/), which blocks
browsers that fetch too many tiles. Backups leave the tiles out.

If the map shows "Access blocked" or stays grey, the App log names the tile
server that refused. Set `tile_url` to another server.

## Sensors

If Home Assistant has an MQTT broker, such as the Mosquitto app, the App adds
a device called Overflights with four entities. They count only aircraft within
`default_radius_km` (the Overhead sensor: the page's radius slider) and below
`default_max_altitude_ft`. Demo passes never
count. The App publishes a change within 5 seconds.

| Entity | State |
| --- | --- |
| `sensor.overflights_today` | Overflights since midnight. Long-term statistics keep the daily totals. |
| `sensor.overflights_last` | Callsign of the latest overflight. Attributes: time, distance, altitude, hex, kind (arrival, departure, transit or unknown). |
| `sensor.overflights_overhead` | The number of aircraft overhead now, within the page's radius. `radius_km` gives that radius. Other attributes describe the nearest: callsign, hex, registration, type, icao_type, operator, origin, origin_name, destination, destination_name, route_plausible, altitude_ft, distance_km, speed_kt, photo. `aircraft` lists the callsigns of all of them. |
| `binary_sensor.overflights_receiver` | Off when the App has not read the receiver for 2 minutes. |

## Storage

The database is `/data/overflights.db`. A pass takes about 2.5 KB. Backups
stop the App for the few seconds the copy takes.
