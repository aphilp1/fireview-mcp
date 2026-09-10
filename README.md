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
   RAWS (fire-weather stations, nationwide, including real fuel moisture/
   temperature where reported); Montana's own state Mesonet (231 stations,
   Montana queries only — a richer, separate network from IEM's MT_* feed,
   see `recorder/mt_mesonet.py`); SNOTEL ridge-wind stations via NRCS AWDB;
   State DOT road cameras (currently Montana and South Dakota, via the
   Iteris ATIS platform).
2. **Radiosonde Soundings** — every real upper-air site within 300 miles,
   with a dead-reckoned ascent flight track per site (real wind/height data
   where available, physical standard-atmosphere estimates elsewhere,
   clearly labeled either way). CONUS sites via NWS's `product.php`, global
   fallback via IGRA.
3. **Active Fire Detections** — VIIRS (375m) and MODIS (1km) active-fire
   hotspots from NASA FIRMS, always shown even at a real zero.
4. **Satellite** — GOES-East/West GeoColor (true color) + Infrared imagery,
   real MODIS/VIIRS orbital ground tracks; see below for detail. Also:
   MODIS Terra/Aqua daily true-color imagery; Landsat 8 & 9 scenes covering
   the full search radius; NEXRAD station reflectivity/velocity as
   toggleable animated WMS layers.

### GOES GeoColor + Infrared

Two independently-toggleable satellite layers, both from NASA GIBS's public
WMTS service (no API key):

- **GeoColor (true color)** — `ABI_GeoColor`, GOES's natural-color composite.
- **Infrared (Band 13, day+night)** — `ABI_Band13_Clean_Infrared`, cloud-top
  temperature; useful after dark or through smoke haze when GeoColor goes
  dark.

**GOES-East vs GOES-West is chosen automatically** by the queried point's
longitude (split at -105°) — whichever satellite actually has useful
coverage there, not a user toggle. Tiles render in a dedicated Leaflet pane
(`goesPane`, z-index 350) specifically so the dashboard's dark-mode CSS
filter (applied to the base OSM tile pane) doesn't invert their real colors.

**Animation** — the ▶ Animate control (¼×–2× speed) works on whichever of
the two products is currently checked. It probes the last ~14 GIBS 10-minute
time steps with a single lightweight test-tile fetch each (GIBS steps are
often missing), keeps only the ones that actually returned imagery, and
cycles those. The checkbox for the animating product stays checked and
enabled throughout — unchecking it (or hitting Stop) always cleanly tears
the animation down, no disabled/stuck states.

Verified live 2026-09-09 against a real CONUS point: real natural-color
GeoColor imagery (correct terrain/cloud/ocean colors, no inversion), real
IR cloud-top imagery showing genuine convection, a full animate → stop
cycle with the checkbox state correct throughout, and zero console errors.

**Fire perimeter** — the real WFIGS-mapped polygon when available.

### Ground Sensor Trends

A "📈 View Trends" button (Sensor Systems panel, enabled whenever the current
query has qualifying stations) opens a draggable, closeable panel with real
historical charts — wind, gust, temp, RH — combined into one area-averaged
line per sensor type (Airport/Road Weather/Remote Sensor/Montana
Mesonet/SNOTEL), switchable across four windows: 6h, 24h, 15d, 30d.

**Combining, not per-station:** each line is the real average across every
currently-reporting station of that type within the 75-mile radius, not one
representative station. A timestamp where only some stations reported still
averages just those; a timestamp with no real reports from any station is a
real gap in the line — never interpolated or estimated.

**Two real data paths per network**, because the underlying APIs differ:
6h/24h windows are hourly bins from each network's raw observations; 15d/30d
windows are daily bins. For the IEM networks (Airport/Road Weather/Remote
Sensor) specifically, IEM's daily archive has no separate daily-average
temp/RH field, only min/max — the 15d/30d temp/RH value is the midpoint of
that real day's recorded min/max, a labeled derived approximation, not a
fabricated observation. Wind/gust at daily granularity are IEM's own real
daily average/max.

**RAWS has no trend line** — no real, keyless historical archive for it was
found. WRCC's own historical system requires a password beyond ~90 days
with no verified station-id crosswalk to NIFC's live feed; NOAA's
`weather.gov/wrh/timeseries` tool works but only by spoofing a Synoptic API
key that's embedded in a public weather.gov JS file for weather.gov's own
use — explicitly ruled out as out of scope for this project. RAWS still
shows full live current conditions, including real fuel moisture/
temperature, on the map itself; it's just absent from the trend panel.

**Performance:** the backend has no batched historical endpoint for IEM, so
each of the three IEM networks is capped at 15 representative stations for
the combined average (SNOTEL and Montana Mesonet have no such cap — both
support real batched multi-station queries). The first `/api/trends` fetch
after a new search/query is the only one that hits the network — it already
returns all four windows in one response, so switching between them
afterward is instant, cached client-side until the next search/query.

## Backend

- `build_sensor_snapshot.py` — `sensors_around_point(lat, lon, radius_km)`
  is the reusable core (every fetch layer parallelized). `build_snapshot
  (fire_name, radius_km)` wraps it with WFIGS fire resolution + perimeter.
- `api_server.py` — a small `ThreadingHTTPServer`, CORS + no-cache,
  `/api/fire`, `/api/point`, `/api/tle` (GET), `/api/trends` (POST — real
  historical ground-sensor data, see `recorder/trends.py`).
- `recorder/` — one module per real data source (WFIGS, IEM Mesonet, NRCS
  AWDB, NWS/SPC/IGRA soundings, Iteris state DOT cameras, NASA FIRMS,
  CelesTrak, NIFC RAWS, Montana Mesonet, `trends.py` for real historical
  ground-sensor data).

## Known gaps

- Radiosonde soundings: CONUS uses NWS's near-immediate `product.php`;
  Alaska/Hawaii use SPC's near-immediate live text-sounding feed (see
  `recorder/spc_sounding.py`); everywhere else (territories) still falls
  back to IGRA (~1–2 day lag).
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
