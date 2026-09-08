# FireView-MCP — Architecture Sketch

**Status: design in progress, build starting 2026-08-03 (moved up from the original
"after Aug 4" queue date at the user's direction — "I want to do everything planned").**

**Naming note:** the product/brand name is **FireView** — same name as the closed
Silvertip project. The two live in separate folders on disk
(`Documents\FireView\` for the closed Silvertip artifact, `Documents\FireView-MCP\`
for this generalized system) purely to avoid a filesystem collision; this mirrors
the existing `FireView` / `FireView-public` sibling-folder pattern already in use.
**They are never merged** — this is a hard standing rule for this user, confirmed
repeatedly across other fire-tracking projects (FireObservation/AircraftWatch/
FireFlight all stay standalone despite subject overlap). This document generalizes
the *pattern* Silvertip proved out, not the Silvertip folder itself, which stays
exactly as it is, closed and untouched.

## The idea

Generalize what was done for Silvertip — both the hourly observation record
(FireView) and the forecast series that ran alongside it — into something that
works for any US wildfire, CONUS/Alaska/Hawaii, driven by a fire name instead of a
hand-written handover document. Given a fire, do everything that was done for
Silvertip: resolve it, build a 48-hour best-available forecast around it, record
its actual conditions hourly, and produce a consolidated report reconciling the
two — the same shape as `SILVERTIP_CONSOLIDATED_FINAL_REPORT.md`, generalized.

Exposed as an MCP server so any Claude session (or other MCP client) can start,
check, and pull data from a fire watch with a tool call instead of a bespoke build
each time.

## Three separable pieces

1. **The recorder** — resolves a fire's location, figures out which regional data
   sources apply, fetches them, decodes them, writes an append-only hourly record.
   This is what FireView (the Silvertip project) did. Python library/CLI, not an
   MCP concept by itself.
2. **The forecaster** — pulls the same real forecast inputs the Silvertip forecast
   series actually used, and builds a 48-hour best-available fire weather forecast
   around NWS SPC Fire Weather Outlook products. New work — Silvertip's forecast
   series wasn't built by FireView itself, but its real, documented inputs and
   process are the model for this piece (see below).
3. **The MCP server** — a thin control/query layer on top of the recorder and the
   forecaster. Tools to start a watch, check on it, pull its data, and pull its
   forecast. The server does not itself run the clock — see "Who actually runs the
   clock" below.

## 1. The recorder

### Fire resolution

Given a name string ("Silvertip"), query WFIGS Incident Locations Current
(`WFIGS_Incident_Locations_Current`, same service FireView already uses) filtered by
`IncidentName LIKE '%name%'`. Returns centroid lat/lon, state, acreage, containment,
personnel, discovery date. If more than one active incident matches the name,
surface the ambiguity rather than guessing — ask which one, the same way a human
would.

### Region classification

First real branch point. Data source availability is fundamentally different in
three regions:

| Region | Surface stations | Radiosondes | Ridge/high-elev wind | Point soundings |
|---|---|---|---|---|
| CONUS | IEM Mesonet ASOS/RWIS/RAWS(DCP), dense | NWS upper-air network, dense | NRCS SNOTEL, common in the mountain west | College of DuPage GFS/NAM, confirmed working |
| Alaska | IEM has `AK_ASOS`; RAWS/DCP coverage untested, likely sparse | Sparse (Anchorage, Fairbanks, a handful more) | SNOTEL exists in AK but density unknown | GFS is global so the *request* should work; untested whether the specific point-sounding tool covers AK cleanly |
| Hawaii | IEM `HI_ASOS` exists; RAWS coverage unknown, terrain-driven micro-climates make single-station representativeness weak | Only Hilo (PHTO) reliably | No SNOTEL (not snow country) — no ridge-wind proxy at all | Same global-GFS caveat as Alaska |

None of this is assumed — the FireView handover doc's rule ("test every endpoint
fresh, record the answer, don't assume a prior matrix carries over") applies
per-region, doubly so the first time a new region is ever used. Expect the first
Alaska or Hawaii fire to surface real gaps that have to be handled with an honest
"not available here," not a forced substitute.

### Station network resolution (replaces FireView's hardcoded MT/ID/WA list)

- Determine which states fall within `radius_km` (FireView used 260 km) of the
  fire's centroid.
- Build IEM network codes dynamically: `{STATE}_ASOS`, `{STATE}_RWIS`, `{STATE}_DCP`
  (RWIS not meaningful outside states with a DOT road-weather program — don't
  request it blind).
- Fallback for anything IEM doesn't cover: `api.weather.gov/points/{lat},{lon}/stations`,
  coarser but works anywhere in the US including AK/HI/territories.

### Radiosonde site resolution (replaces hardcoded TFX/OTX)

Build a small static reference table of NWS upper-air stations (~92 across the US
and territories, this basically never changes) with lat/lon and WMO ID. Compute
nearest one or two to the fire at watch-start time. Same decode path FireView
already validated (`forecast.weather.gov/product.php?product=MAN`) — the FM-35
decoding rules (temperature-sign parity, dewpoint-depression threshold,
wind-direction-carries-100kt digit) are universal, not Montana-specific, so that
code ports directly.

### Ridge-level wind proxy

NRCS SNOTEL, nearest site with a wind element (`WSPDV`/`WSPDX`/`WDIRV`), within
some reasonable distance. **Explicitly absent in Hawaii and much of the eastern
US** — the recorder needs to say "no ridge-level proxy available for this fire"
rather than silently omitting the section.

### Point forecast soundings

College of DuPage's `fsound` endpoint takes any lat/lon and GFS is a global model,
so the request *should* work anywhere — but this is exactly the kind of assumption
the handover doc got burned on before (stale SPC products, "GEM" silently
returning NAM data). Test it fresh for the actual fire location before relying on
it, every time, not just once per region.

### Sector classification (upwind/downwind/cross-stream)

This is the one piece that **cannot be auto-derived** — FireView's 180–330°/20–140°
split is specific to Silvertip's known west-to-east frontal flow, not a general
fact about geography. The generalized recorder needs the prevailing wind direction
as a **required input at watch-start** (a forecaster's judgment call, same as a
human deciding it for Silvertip), with a tool to update it if the synoptic pattern
changes mid-event.

### Output conventions — fixed, not regional

These are FireView's standing rules, baked into the recorder's core, not
re-decided per fire:
- Append-only, one file per cycle, nothing ever edited after the fact.
- `NO DATA` written explicitly wherever a source doesn't carry a value — never
  filled from a model, a neighboring station, or a previous cycle.
- Every fetched product's issue date/time read and checked before use (the "stale
  2023 SPC product" trap).
- Capture and interpretation visibly separated in every entry.
- Plain English, every model/source named in full on first use, no invented
  shorthand.

## 2. The forecaster

Silvertip's forecast series (Forecast No.1–5) was not built by FireView's own
recorder code — it ran as a separate, parallel effort — but its real, documented
data sources and structure are exactly the model to generalize, per the
consolidated report's own reference list:

### Real inputs the forecaster generalizes from

- **NOAA SPC Fire Weather Outlook**, Day 1/Day 2 — the anchor product this whole
  piece is built around, per the user's direction.
- **GEFS** (31-member ensemble) and **ECMWF ENS** (51-member ensemble) — the two
  global ensembles whose divergence drove the entire Silvertip forecast question.
- **GFS** and **NAM** deterministic models, plus **HRRR** (convection-allowing)
  and **DWD ICON** as a third global-model cross-check.
- **Open-Meteo "best_match"** blended API for fire-point surface estimates —
  labelled a model blend, never an observation, in every output.
- **College of DuPage NEXLAB** point-forecast soundings at the fire's exact
  coordinates — the tool that resolved Silvertip's ridge-vs-surface inversion
  question when the coarse ensembles couldn't.
- **WindNinja**, terrain-corrected wind simulation over real SRTM 30 m elevation,
  for point-scale downscaling where global models can't resolve terrain.

### The 48-hour best-available forecast

Built the same way Forecast No.1 through No.5 evolved for Silvertip: not one
static document, but a locked baseline (the first issue, timed against the
digging synoptic feature nearest the fire) that gets **re-verified against fresh
data on a cadence, not silently rewritten**. Each subsequent issue:
- States what's changed since the last issue and why (a specific new balloon, a
  fresh model cycle, an SPC amendment).
- Keeps the locked baseline's falsification test visible rather than moving the
  goalposts — Silvertip's discipline of pre-registering a decision rule (the
  700-hPa threshold) and scoring against it, even when a mid-event analysis
  argued otherwise, is the single most transferable lesson from that report
  (Finding 2) and is a hard requirement here, not a nice-to-have.
- Ends with an explicit scorecard once the 48-hour window closes: each testable
  claim marked hit/miss/partial against what the recorder actually measured —
  which is exactly why the forecaster and the recorder must share a fire_id and
  read each other's output, not run as unrelated tools.

### What's genuinely new here (no direct Silvertip precedent)

- Automating the "issue a new forecast when something material changes" judgment
  call that a human made by hand for Silvertip No.1–5. Needs an explicit trigger
  policy (new model cycle available, new balloon posted, SPC amendment issued),
  not a fixed timer — Silvertip's own issues were event-driven, not scheduled.
  Prevented from becoming a real risk (over-issuing, chasing noise) is more open
  design work, not settled here.
- Region portability of SPC Fire Weather Outlook itself — SPC's outlook domain
  and product structure outside CONUS is untested; Hawaii and Alaska fire weather
  guidance may come from a different NWS product entirely. Test fresh per the
  same rule as the recorder's region table, don't assume.

## 3. MCP server — tool surface (draft)

Recorder tools:
- `start_fire_monitor(name, prevailing_wind_deg, cadence_minutes=60, radius_km=260)`
  — resolves the fire via WFIGS, classifies region, builds the per-fire
  data-source config, creates the storage folder, registers it as active. Returns
  a `fire_id` and a summary of which data sources were found reachable for this
  specific location (not assumed from a prior fire).
- `run_cycle(fire_id)` — executes one recording sweep for a fire immediately (what
  a scheduler calls hourly, but also directly callable for a manual catch-up —
  exactly the move used to close the Silvertip recording gap on 2026-08-02).
- `get_fire_status(fire_id)` — last successful cycle, any gaps, next scheduled
  run, which data sources are currently down.
- `list_active_monitors()` — every fire currently being tracked.
- `get_cycle_log(fire_id, cycle_number | "latest")` — raw log text or a
  structured summary.
- `get_timeseries(fire_id, format=csv|json)` — the reconstructed long-format
  dataset (FireView's `SILVERTIP_TIMESERIES.csv` pattern), the form meant to feed
  a later hindcast run or the forecaster's own scorecard.
- `set_prevailing_wind(fire_id, degrees)` — update the sector classification if
  the event's flow pattern changes.
- `stop_fire_monitor(fire_id)` — end recording (containment, decision to stop),
  archive the folder, leave the record exactly as it stands.

Forecaster tools:
- `issue_forecast(fire_id, reason)` — pulls current SPC/GEFS/ECMWF/GFS/NAM/HRRR/
  ICON/College of DuPage/WindNinja inputs, builds the next numbered forecast
  issue, states explicitly what changed since the prior issue and why (`reason`
  is required, not optional — no silent re-issues).
- `get_forecast(fire_id, issue_number | "latest")` — a specific issue or the
  current one.
- `score_forecast(fire_id)` — once the forecast window closes, reconciles every
  testable claim in the locked baseline against what the recorder actually
  measured; the generalized version of Silvertip's Section 5.1 scorecard.
- `build_consolidated_report(fire_id)` — once both the recorder and forecaster
  are stopped/closed for a fire, generates the generalized equivalent of
  `SILVERTIP_CONSOLIDATED_FINAL_REPORT.md`.

## Who actually runs the clock

MCP servers are request/response — they don't run a background scheduler on
their own. Two options, not decided yet:

- **One shared Windows Scheduled Task** that wakes up every N minutes and calls
  `run_cycle()` (and, on its own separate/coarser cadence, checks whether
  `issue_forecast()` conditions are met) on every currently-active fire — avoids
  one scheduled task per fire, which would proliferate fast if several fires are
  tracked at once.
- **Per-fire scheduled task**, mirroring exactly what FireView does today —
  simpler to reason about per fire, but doesn't scale past a handful of
  simultaneous watches.

Leaning toward the shared-task option, but this is worth deciding deliberately
once there's a real second fire to test against, not guessed now.

## Storage layout (draft)

```
Documents\FireView-MCP\
  fires\
    <fire_id>\
      cycle_logs\            (append-only, same format as FireView)
      forecasts\
        forecast_001.md, forecast_002.md, ...   (numbered issues, never edited after posting)
        scorecard.md          (written once, at window close)
      timeseries.csv
      config.json             <- resolved data sources, radius, prevailing wind, region
      consolidated_report.md  (generated once both pieces are stopped)
      dashboard.html           (optional, opt-in per fire — see below)
```

## Open questions, deliberately unresolved here

- **Public dashboard per fire, like FireView's GitHub Pages site** — nice to have,
  but shouldn't auto-create a public repo for every fire without being asked each
  time. Default off, opt-in per `start_fire_monitor` call.
- **What counts as "done" for a fire** — full containment? A time cutoff the user
  sets, like Silvertip's original Aug 4 window (itself later shortened to Aug 3)?
  Needs to be an explicit stop, not inferred.
- **Forecast re-issue trigger policy** — see "What's genuinely new" above. Needs
  a concrete rule before this ships, or it risks either missing real changes or
  spamming re-issues.
- **Alaska/Hawaii data-source gaps, for both the recorder and the forecaster** —
  genuinely unknown until tested against a real event there. Don't pre-build
  fallback logic for gaps that are still speculative; build it when the first
  real AK/HI fire surfaces the actual gap.

## What ports directly from Silvertip with near-zero change

- FM-35 balloon decode logic (temperature-sign parity, dewpoint-depression rule,
  wind-direction 100kt-carry digit) — these are protocol facts, not Montana facts.
- Great-circle distance/bearing computation.
- The `NO DATA` / stale-flagging / capture-vs-interpret log structure.
- The timeseries-reconstruction approach (parse every cycle log into one
  long-format table).
- The forecast series' own discipline: locked baseline, pre-registered decision
  rule, explicit scorecard, disclosed corrections rather than silently fixed
  ones.

## What's genuinely new work

- Fire-name → location resolution with disambiguation.
- Region classification and per-region data-source selection, for both the
  recorder and the forecaster.
- The radiosonde-site and station-network lookup tables (currently hardcoded to
  Silvertip).
- The forecast re-issue trigger policy.
- The MCP tool layer itself and the shared-vs-per-fire scheduling decision.
