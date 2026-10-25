# Changelog

## 0.9.2

- The map draws the Last overhead aircraft's path in bright yellow, instead
  of a ring at its closest point.

## 0.9.1

- When no aircraft is within the radius, the Overhead now card becomes
  **Last overhead**. It shows the latest aircraft whose closest point came
  within the radius: when, how close and how high, its class, and the same
  details as a live aircraft. The map marks its closest point with a ring.

## 0.9.0

- The page's radius slider is shared. The App keeps its value, every browser
  opens with it, and an open page follows a change made elsewhere.
- The slider sets the radius of both the Overhead now card and
  `sensor.overflights_overhead`, so they always agree. The sensor has a new
  attribute, `radius_km`.
- The option `now_radius_km` is gone.

## 0.8.2

- The Overhead now card uses the page's radius slider, and updates as the
  slider moves. `now_radius_km` now sets only `sensor.overflights_overhead`.

## 0.8.1

- The new option `now_radius_km` (1 km) sets the area of the Overhead now
  card and `sensor.overflights_overhead`. Before, they used
  `default_radius_km`, which still sets the overflight counts.

## 0.8.0

- An **Overhead now** card at the top of the page shows each aircraft inside
  the overhead radius and below the overhead altitude limit: its callsign,
  registration, operator, type, route, photo, altitude and speed. The map
  marks each one. The card updates every 5 seconds.
- The App looks up registration, type, operator, route and photo at
  adsbdb.com, once for each aircraft and callsign. If the route does not fit
  the aircraft's position, the card says that it may be out of date. The new
  `online_lookup` option turns the lookups off.
- A new sensor, `sensor.overflights_overhead`, counts the aircraft overhead.
  Its attributes describe the nearest one. The sensors now update every
  5 seconds instead of 15.

## 0.7.4

- The App fetches the map tiles, keeps them for 30 days, and serves them to
  the page. Before, each browser fetched them from OpenStreetMap, which can
  block an address that fetches too many and then shows "Access blocked".
- The tiles come from `tile.openstreetmap.de`. The new `tile_url` option sets
  another server.

## 0.7.3

- The version stamp on the page's script and stylesheet links covers every
  static file, including Leaflet. Before, a browser kept its cached Leaflet
  after an update that changed only Leaflet.

## 0.7.2

- The bundled Leaflet no longer names a source map that the App does not
  ship, so browser developer tools show no 404 for `leaflet.js.map`.

## 0.7.1

- The App stops at once when the Supervisor stops it. Before, it ignored the
  stop signal, so each stop or restart waited 10 seconds and then killed it.
- The page stops polling while its tab is hidden. If Home Assistant's
  session for the page has expired (HTTP 401), the status line says to
  reload the page, and polling stops. While the App restarts (HTTP 502), the
  status line says so and the page keeps trying.

## 0.7.0

- The option `airport`: enter an ICAO or IATA code, such as EDDB or BER. The
  App looks up the airport position and its runway ends in a copy of the
  OurAirports database, without going online. `airport_latitude`,
  `airport_longitude` and `runways` now only override the lookup.
- A README on the App's Info tab explains how to install and set it up.

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
