# FireView — Status (as of 2026-09-05)

FireView is a single, live, national fire-weather sensor dashboard. Search
any active US fire by name, or click anywhere on the map, and it pulls the
real sensor network within a fixed 75-mile radius — no per-fire static
pages, no fabricated data. Every value shown is either a real live reading
from a named source or explicitly marked as missing/estimated.

This supersedes `ARCHITECTURE_SKETCH.md` (2026-08-03), which was written
before the recorder/dashboard existed and described a broader planned
system (recorder + forecaster + MCP tool layer). Only the recorder +
live dashboard piece has actually been built; the forecaster and MCP tool
layer are still just design notes in that file.

## Running it

Two local servers, both required:

```
python api_server.py 8940      # JSON API: /api/fire?name=, /api/point?lat=&lon=, /api/tle
python serve_dashboard.py 8930 # serves dashboard.html (no-cache HTTP server)
```

Then open `http://127.0.0.1:8930/dashboard.html`. `dashboard.html` is a
deployed copy of `dashboard_template.html` — always edit the template and
re-copy (`cp dashboard_template.html dashboard.html`), never edit the
deployed copy directly, or the next template edit will silently overwrite it.
**`api_server.py` must be restarted after any change to
`build_sensor_snapshot.py` or anything under `recorder/`** — it does not
hot-reload.

## What it shows

**Search or click** — a header search box resolves any fire name via live
WFIGS; clicking anywhere on the map queries that exact point instead. A
small crosshair (⌖) toggle near the zoom control controls whether clicking
the map queries a point at all: armed (default, crosshair cursor) fires a
query; it auto-disarms after a result loads (cursor reverts to a normal
pannable grab hand) so panning around a result doesn't trigger a new query
on every click — click the toggle to re-arm. Only one view (fire or point)
is ever active at a time.

**SENSOR SYSTEMS panel** (left sidebar) — collapsible (−/+ in its header)
and draggable (drag by the header title bar; first drag promotes it out of
the sidebar to a free-floating `position:fixed` panel). Four logical
groups:

1. **Ground Sensors** — real-time surface wind stations within 75 mi:
   Airport (ASOS), Remote Sensor (DCP), Road Weather (RWIS) via IEM Mesonet
   (wind-instrumented only); SNOTEL — Ridge Wind via NRCS AWDB
   (wind-instrumented only, ~20% of all SNOTEL sites); State DOT Road
   Cameras — Montana and South Dakota only (verified Iteris ATIS platform
   match; Georgia/Kansas/West Virginia do NOT share this architecture).
2. **Radiosonde Soundings** — every real site within **300 miles** (a
   named constant, `SOUNDING_RADIUS_MI` in `build_sensor_snapshot.py` —
   explicitly asked-and-confirmed after measuring the full ~87-station
   national network at a real 18.6s fetch, too slow to run on every
   query). This section is now just a scope note + one toggle + a
   one-line site-count summary — no per-site data dump in the panel
   itself. The toggle ("Track + 300mi radius on map") turns on: (a) a
   dashed aqua circle showing the real 300mi search boundary, and (b) each
   site's real ascent flight-track (dead-reckoned from real wind data,
   physically real US Standard Atmosphere heights where the report itself
   doesn't carry a real height) with one clickable point per real level —
   click any point for that level's full data (height, temp, dewpoint,
   wind), and the first (launch) point on each track carries the full site
   identity (name, distance, launch time) that used to live in the sidebar.
   Both CONUS (near-immediate) and IGRA (~1–2 day lag, global fallback)
   sourced sites are supported; IGRA-sourced points have real height but no
   temp/dewpoint (that field genuinely isn't parsed from the archive).
3. **Active Fire Detections** — always shown even at a real zero (a fire
   with no current hits still gets both rows, dimmed, not hidden):
   VIIRS Active Fire (375m, Suomi NPP + NOAA-20 + NOAA-21, NASA FIRMS
   keyless regional CSVs, CONUS+HI+AK; Esri/NIFC mirror fallback for
   territories) and MODIS Active Fire (1km, Terra + Aqua, same FIRMS
   feeds, no territory fallback). Both are a rolling 24h window (a
   property of the real source).
4. **Satellite** — GOES-East/West GeoColor + Infrared (Band 13,
   day+night), auto-selected by longitude, NASA GIBS WMTS, rendered in a
   dedicated Leaflet pane to escape the basemap's dark-mode CSS filter.
   Includes a real animated loop (▶ Animate, ¼×–2× speed) for whichever
   product's checkbox is checked, built by probing ~14 recent 10-minute
   GIBS time steps and cycling only the ones that actually have imagery;
   the animated product's checkbox shows checked+disabled while playing
   (accurately reflects "on, controlled by animation" instead of reading
   as a mismatch). Also: MODIS Terra/Aqua true-color daily global imagery
   (not fire-gated) — the date-availability check probes at the **same
   zoom level the tiles will actually render at** (a real bug: GIBS
   completes coarser zooms of a daily mosaic before finer ones, and Terra
   vs Aqua genuinely complete at different times since they have different
   real overpass times — Terra ~10:30am, Aqua ~1:30pm local, so at any
   given moment one can be ready while the other isn't, same zoom, same
   code). And real MODIS/VIIRS orbital ground tracks (live TLEs from
   CelesTrak via `/api/tle`, propagated client-side with satellite.js) —
   toggle per sensor family, shows the real current orbit path + a
   live-updating position marker, clearly labeled as propagated/modeled,
   not GPS-observed.

**Fire perimeter** — real WFIGS-mapped polygon when available; a flame
glyph fallback only when WFIGS hasn't mapped that incident yet.

**75-mile search radius** — shown as a dashed circle (exact 120.7008 km).

## Backend

- `build_sensor_snapshot.py` — `sensors_around_point(lat, lon, radius_km)`
  is the reusable core (every fetch layer parallelized via
  `ThreadPoolExecutor`). `build_snapshot(fire_name, radius_km)` wraps it
  with WFIGS fire resolution + perimeter.
- `api_server.py` — `ThreadingHTTPServer`, CORS + no-cache, `/api/fire`,
  `/api/point`, `/api/tle` (CelesTrak has no CORS header, so TLEs are
  fetched server-side and cached 6h).
- `recorder/` — one module per real data source: `fire_resolution.py`,
  `region.py`, `perimeter.py` (WFIGS); `stations.py` (IEM Mesonet);
  `snotel.py` (NRCS AWDB); `balloons.py` + `radiosonde_stations.py` +
  `igra.py` + `drift_track.py` (soundings + flight-track dead-reckoning);
  `iteris_rwis.py` (state DOT cameras); `firms_active_fire.py` (NASA FIRMS
  VIIRS+MODIS, primary); `viirs_fire.py` (Esri/NIFC VIIRS mirror, territory
  fallback only); `orbital_tracks.py` (CelesTrak TLE fetch/cache).

## Known gaps (real, documented, not silently papered over)

- Radiosonde soundings: Alaska/Hawaii/territories have no confirmed working
  fetch via the CONUS MAN-product path — falls back to IGRA (~1–2 day lag).
- State DOT cameras: Georgia, Kansas, West Virginia confirmed NOT to share
  Montana/South Dakota's Iteris platform — separate integrations needed.
- MODIS active-fire: no territory fallback (no verified global keyless
  MODIS point source found yet).
- IGRA-sourced radiosonde track points have real height but no temp/
  dewpoint (not parsed from that archive).
- Sensor-listing panel styling still hasn't had the full RapidWatch/
  StormWatch-level visual redesign pass the user originally asked for.

## Not yet built

- Draggable/movable DOT-camera image popup.
- MCP tool-server layer described in `ARCHITECTURE_SKETCH.md` (never built
  — the live dashboard superseded that plan).
- Forecaster (48h SPC-Fire-Weather-Outlook-driven series) — never built.

## Backups

- `OneDrive\FireView-MCP_backup_20260803_230715.zip` — pre-dashboard,
  recorder-library-only state (2026-08-03).
- `OneDrive\FireView-MCP_backup_20260904_192720.zip` — live dashboard, GOES
  animation, VIIRS/MODIS active fire.
- `OneDrive\FireView-MCP_backup_20260905_163259.zip` — this backup:
  query-armed toggle, collapsible/draggable Sensor Systems panel, IR +
  MODIS imagery + orbital paths, full radiosonde flight-track
  visualization + 300mi boundary circle, the MODIS per-zoom
  date-resolution fix, launch dates restored to the sidebar panel, and a
  full `--slate`/`--mute` → `--ink` contrast sweep across the whole
  dashboard (not just the previously-reported spots).

Not a git repository — no `.git` here, nothing to push. This file plus the
zip backups are the durable record of state.
