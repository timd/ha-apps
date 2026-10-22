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

If you set `airport_latitude` and `airport_longitude`, an arrival must also end
at least 2 km closer to that airport than it started, and a departure 2 km
further away. A pass that fails this check is a transit. Without an airport, the
App counts every low descent as an arrival, for any airfield.

On the map, click a class in the legend to hide or show its paths. The
browser remembers the choice. The Type filter above the charts limits the
whole page to one class.

## Paths to the airport

With an airport set, the App also stores positions within
`airport_radius_km` (25 km) of the airport, for aircraft that also come within
the capture radius of the house. Arrivals and departures then continue on the
map toward the airport, until the receiver loses sight of them. An aircraft
that only crosses the airport area is not a pass, and the App deletes it.

A receiver some distance away cannot see aircraft low over the airport. Near
the ground, arrivals and departures disappear several kilometres from the
runway. If you list the runways in `runways`, the map joins each arrival's
last position, and each departure's first, to a runway end with a dashed line.
The App joins only an aircraft within 25° of a runway's extended centreline,
and picks the nearest centreline. An aircraft that the receiver lost on a
downwind or base leg still has a turn to fly, so its path stays open.
The dashed line is an estimate, not a received path. Without runways, the
line goes to the airport position.

Give each runway as its two ends, `lat,lon,lat,lon`. For Berlin
Brandenburg:

```yaml
runways:
  - 52.37743,13.52611,52.36768,13.48500
  - 52.35843,13.52317,52.34543,13.46843
```

The App classifies passes when the page asks for them, so a change to these
options also applies to the passes that are already stored.

The page filters by radius and by altitude at the closest point. The radius
is only a view filter, so you can change it at any time without losing data.

## Options

| Option | Meaning |
| --- | --- |
| `receiver_url` | The receiver's data folder, which holds `aircraft.json` and `receiver.json`. |
| `latitude`, `longitude` | The house position. If empty, the App reads it from `receiver.json`. |
| `airport_latitude`, `airport_longitude` | Optional. The main airport near the house, used to check arrivals and departures. |
| `airport_radius_km` | Positions within this distance of the airport are stored too. 0 turns this off. |
| `runways` | Optional. Each runway's two ends as `lat,lon,lat,lon`, for the dashed lines on the map. |
| `capture_radius_km` | Positions further away are not stored, except near the airport. Only aircraft that come this close are passes. |
| `poll_seconds` | How often the App reads the receiver. |
| `retention_days` | Passes older than this are deleted. |
| `default_radius_km` | What counts as overhead: the page's radius until a viewer changes it, and the radius for the sensors. |
| `default_max_altitude_ft` | The altitude limit for the page and the sensors. 0 means any altitude. |
| `demo_data` | Adds 60 days of demo passes, made from the receiver's last hour of real tracks. Turn it off to delete them. |

## Sensors

If Home Assistant has an MQTT broker, such as the Mosquitto app, the App adds
a device called Overflights with three entities. They count only passes within
`default_radius_km` and below `default_max_altitude_ft`. Demo passes never
count.

| Entity | State |
| --- | --- |
| `sensor.overflights_today` | Overflights since midnight. Long-term statistics keep the daily totals. |
| `sensor.overflights_last` | Callsign of the latest overflight. Attributes: time, distance, altitude, hex, kind (arrival, departure, transit or unknown). |
| `binary_sensor.overflights_receiver` | Off when the App has not read the receiver for 2 minutes. |

## Storage

The database is `/data/overflights.db`. A pass takes about 2.5 KB. Backups
stop the App for the few seconds the copy takes.
