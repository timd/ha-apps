# Changelog

## 0.6.5

- The map comes first on the page, above the charts.

## 0.6.4

- The map zooms in smaller steps: half a level for each button press or
  wheel notch, and it can rest between whole levels. The first view fits
  the house area and the airport more closely.

## 0.6.3

- Map tracks fade with age: full strength for the last day, medium for the
  last week, faint for older ones. The legend shows the three steps. Opacity
  no longer shows how many aircraft crossed a point.

## 0.6.2

- The map draws transits first, then arrivals, then departures on top, so
  arrivals and departures stay visible where they cross busy transit routes.
  A pixel's strength now counts only the tracks of the class drawn there.

## 0.6.1

- The Latest overflights table has its own period: the last hour, day or
  week, or all time. It still uses the radius, altitude and type filters. The
  browser remembers the choice.
- The table shows 100 rows at first. "Show 100 more" adds rows.

## 0.6.0

- With an airport set, the App also stores positions within
  `airport_radius_km` (default 25 km) of it. Arrivals and departures continue
  on the map toward the airport. Passes that never come within the capture
  radius of the house are deleted.
- The option `runways`: the map joins each arrival and departure to a runway
  end with a dashed line, across the part the receiver cannot see. It joins
  only aircraft within 25° of a runway's extended centreline.
- The map opens with the airport in view.

## 0.5.2

- The Trace link opens the ADS-B Exchange map centred on the house, so the
  trace is in view as soon as it loads.

## 0.5.1

- The map legend's classes are buttons: click one to hide or show its paths
  on the map. The browser remembers the choice.

## 0.5.0

- Each pass is an arrival, a departure, a transit, or unclassified, from its
  altitude profile. The map colours paths by class, the table shows it, and
  the Type filter limits the page to one class.
- The options `airport_latitude` and `airport_longitude`: if set, an arrival
  must move toward the airport and a departure away from it.
- The last-overflight sensor has a `kind` attribute.
- The page loads its script and stylesheet by content hash, so a browser
  never mixes an old script with a new page.

## 0.4.1

- The map draws paths 3 px wide, and darker in the light theme.
- The path that you point at in the table is drawn 4 px wide.

## 0.4.0

- First public release. Prebuilt images for amd64 and aarch64.
- The default receiver URL is now `http://piaware.local/skyaware/data`.
- Option descriptions in the configuration screen.

## 0.3.0

- Home Assistant sensors over MQTT: overflights today, the last overflight,
  and receiver connectivity.

## 0.2.0

- The `demo_data` option.

## 0.1.0

- The logger and the page.
