# Home Assistant Apps

Local Apps for the Home Assistant server.

| App | Purpose |
| --- | --- |
| [Overflights](overflights/DOCS.md) | Logs aircraft that pass over the house from the ADS-B receiver and charts when and where they fly. |

## Install on the server

Copy an App's folder to `/addons/<slug>/` on the server. Then open Settings →
Apps → App store, choose **Check for updates** from the menu, and install the
App from **Local apps**. After a change, raise `version` in `config.yaml`,
copy the folder again, and click **Update** (or **Rebuild** if the version is
unchanged).

## Develop locally

```bash
python3 -m venv .venv && .venv/bin/pip install aiohttp
mkdir -p /tmp/overflights && cat > /tmp/overflights/options.json <<'JSON'
{"receiver_url": "http://adsb.home.arpa/skyaware/data", "capture_radius_km": 30,
 "poll_seconds": 5, "retention_days": 365, "default_radius_km": 5, "default_max_altitude_ft": 0}
JSON
cd overflights/app && OVERFLIGHTS_DATA=/tmp/overflights ../../.venv/bin/python main.py
```

The page is then at http://localhost:8099/. Add `?theme=dark` or
`?theme=light` to override the system theme.
