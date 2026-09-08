# FireView

A single, live, national fire-weather sensor dashboard. Search any active US
fire by name, or click anywhere on the map, and it pulls the real sensor
network within a 75-mile radius — no per-fire static pages, no fabricated
data. Every value shown is either a real live reading from a named source or
explicitly marked as missing/estimated.

## Running it

Two local servers, both required:

```
python api_server.py 8940      # JSON API: /api/fire?name=, /api/point?lat=&lon=, /api/tle
python serve_dashboard.py 8930 # serves dashboard.html (no-cache HTTP server)
```

Then open `http://127.0.0.1:8930/dashboard.html`.

`dashboard.html` is a deployed copy of `dashboard_template.html` — always
edit the template and re-copy it, never edit the deployed copy directly.
`api_server.py` must be restarted after any change to
`build_sensor_snapshot.py` or anything under `recorder/` — it does not
hot-reload.

No API keys required. Everything here uses free, public, keyless data
sources.

## What it shows

**Search or click** — a header search box resolves any active US fire by
name via live WFIGS incident data; clicking anywhere on the map queries that
exact point instead. A crosshair toggle near the zoom control arms/disarms
click-to-query so panning doesn't trigger repeat queries.

**Sensor Systems panel** (left sidebar, collapsible and draggable):

1. **Ground Sensors** — real-time surface wind stations within 75 mi:
   Airport (ASOS), Remote Sensor (DCP), Road Weather (RWIS) via IEM Mesonet;
   SNOTEL ridge-wind stations via NRCS AWDB; State DOT road cameras
   (currently Montana and South Dakota, via the Iteris ATIS platform).
2. **Radiosonde Soundings** — every real upper-air site within 300 miles,
   with a dead-reckoned ascent flight track per site (real wind/height data
   where available, physical standard-atmosphere estimates elsewhere,
   clearly labeled either way). CONUS sites via NWS's `product.php`, global
   fallback via IGRA.
3. **Active Fire Detections** — VIIRS (375m) and MODIS (1km) active-fire
   hotspots from NASA FIRMS, always shown even at a real zero.
4. **Satellite** — GOES-East/West GeoColor + Infrared (auto-selected by
   longitude) with a real animated loop; MODIS Terra/Aqua daily true-color
   imagery; Landsat 8 & 9 scenes covering the full search radius; NEXRAD
   station reflectivity/velocity as toggleable animated WMS layers; real
   MODIS/VIIRS orbital ground tracks propagated from live TLE data.

**Fire perimeter** — the real WFIGS-mapped polygon when available.

## Backend

- `build_sensor_snapshot.py` — `sensors_around_point(lat, lon, radius_km)`
  is the reusable core (every fetch layer parallelized). `build_snapshot
  (fire_name, radius_km)` wraps it with WFIGS fire resolution + perimeter.
- `api_server.py` — a small `ThreadingHTTPServer`, CORS + no-cache,
  `/api/fire`, `/api/point`, `/api/tle`.
- `recorder/` — one module per real data source (WFIGS, IEM Mesonet, NRCS
  AWDB, NWS/IGRA soundings, Iteris state DOT cameras, NASA FIRMS, CelesTrak).

## Known gaps

- Radiosonde soundings: Alaska/Hawaii/territories fall back to IGRA
  (~1–2 day lag) — no confirmed fast path there yet.
- State DOT cameras: only Montana and South Dakota share the Iteris
  platform this integrates against; Georgia, Kansas, and West Virginia do
  not and would need separate integrations.
- MODIS active-fire has no verified fallback source for US territories.
- IGRA-sourced radiosonde track points carry real height but no
  temperature/dewpoint (not present in that archive).
- The DOT-camera image popup isn't yet draggable/movable.
- No forecaster (a planned 48h SPC-Fire-Weather-Outlook-driven series) —
  never built; this is a live-conditions dashboard, not a forecast tool.

## License

MIT — see `LICENSE`.
