# Overflights

Overflights logs every aircraft that the ADS-B receiver sees within the capture
radius of the house. Open it from the Overflights item in the sidebar.

## How it works

Every few seconds the App reads `aircraft.json` from the PiAware receiver. It
keeps each aircraft's positions inside the capture radius and groups them into
passes. A pass ends when an aircraft is not seen for 10 minutes. For each pass,
the App records the closest approach to the house. It takes that point from the
straight line between two consecutive positions, so it does not depend on the
moment a position was sampled.

The page filters by radius and by altitude at the closest point. The radius
is only a view filter, so you can change it at any time without losing data.

## Options

| Option | Meaning |
| --- | --- |
| `receiver_url` | The receiver's data folder, which holds `aircraft.json` and `receiver.json`. |
| `latitude`, `longitude` | The house position. If empty, the App reads it from `receiver.json`. |
| `capture_radius_km` | Positions further away are not stored. |
| `poll_seconds` | How often the App reads the receiver. |
| `retention_days` | Passes older than this are deleted. |
| `default_radius_km` | The page's radius until a viewer changes it. |
| `default_max_altitude_ft` | The page's altitude limit. 0 means any altitude. |

## Storage

The database is `/data/overflights.db`. A pass takes about 2.5 KB. Backups
stop the App for the few seconds the copy takes.
