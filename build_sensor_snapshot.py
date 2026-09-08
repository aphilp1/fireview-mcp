#!/usr/bin/env python3
"""
Builds a real-time sensor snapshot around a point: every ASOS/RWIS/DCP
wind-instrumented station within radius_km (live current observations, not
just registry metadata), every wind-instrumented SNOTEL/SNOTEL-Lite station,
and the nearest radiosonde sites' latest soundings (CONUS via the fast
forecast.weather.gov MAN product, falling back to NOAA/NCEI's global IGRA
archive everywhere that doesn't cover -- see recorder/igra.py for the real
latency tradeoff that fallback carries).

sensors_around_point() is the reusable core (used by both this script's
per-fire builds and api_server.py's click-anywhere point queries). build_snapshot()
wraps it with fire resolution + the real WFIGS perimeter polygon.

Writes fires/<fire_id>/sensor_snapshot.json and fires/<fire_id>/config.json,
per the storage layout in ARCHITECTURE_SKETCH.md. No fabricated/interpolated
values: a station or level that fails to fetch or decode is simply omitted,
never guessed.

Usage: python build_sensor_snapshot.py "Silvertip" [radius_km]
"""
import json
import math
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "recorder"))

from fire_resolution import resolve_fire, AmbiguousFireError, FireResolutionError
from region import classify_region
from stations import nearby_states, build_network_codes, fetch_network_currents, fetch_network_stations
from balloons import nearest_sites, sites_within, fetch_latest, parse_message, parse_header_launch_time
import drift_track
from radiosonde_stations import RADIOSONDE_STATIONS
from perimeter import fetch_perimeter
from snotel import fetch_wind_stations, fetch_latest_wind
import igra
import iteris_rwis
import viirs_fire
import firms_active_fire
import nexrad_stations

EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _kt_to_mph(kt):
    return round(kt * 1.15078, 1) if kt is not None else None


def _mps_to_mph(mps):
    return round(mps * 2.23694, 1) if mps is not None else None


def _mps_to_kt(mps):
    return round(mps * 1.94384, 1) if mps is not None else None


# TTAA mandatory-level 2-digit codes -> real pressure in hPa (protocol fact,
# not station-specific). Matches balloons.py's LEVEL_ORDER exactly.
LEVEL_HPA = {"92": 925, "85": 850, "70": 700, "50": 500, "40": 400,
             "30": 300, "25": 250, "20": 200, "15": 150, "10": 100}


def _conus_full_profile(parsed):
    """Every mandatory level the CONUS MAN product actually decoded (not
    just surface+700hPa) -- this IS the "all the available balloon
    information" the user asked for. A level with nothing decoded (both temp
    and wind missing) is skipped rather than shown as an all-blank row."""
    def r1(v):
        return round(v, 1) if v is not None else None
    levels = []
    surf = parsed.get("surface")
    if surf:
        levels.append({
            "label": "Surface", "pressure_hpa": surf.get("pressure_hpa"), "height_m": None,
            "temp_c": r1(surf.get("temp_c")), "dewpt_c": r1(surf.get("dewpt_c")),
            "wind_dir": surf.get("wind_dir"), "wind_kt": surf.get("wind_kt"),
        })
    for code, hpa in LEVEL_HPA.items():
        lvl = parsed.get(code)
        if not lvl or (lvl.get("temp_c") is None and lvl.get("wind_kt") is None):
            continue
        levels.append({
            "label": f"{hpa} hPa", "pressure_hpa": hpa, "height_m": lvl.get("height_m"),
            "temp_c": r1(lvl.get("temp_c")), "dewpt_c": r1(lvl.get("dewpt_c")),
            "wind_dir": lvl.get("wind_dir"), "wind_kt": lvl.get("wind_kt"),
        })
    return levels


def _igra_full_profile(sounding):
    """Every level IGRA's y2d archive actually carries for this launch.
    Real gap, not fabricated: igra.py's parser only extracts pressure/
    height/wind columns (never temp/dewpoint), so temp_c/dewpt_c are always
    None here -- that's an honest reflection of what's parsed, not a bug."""
    levels = []
    for lv in sounding.get("levels", []):
        if lv.get("wind_mps") is None and lv.get("pressure_pa") is None:
            continue
        hpa = round(lv["pressure_pa"] / 100) if lv.get("pressure_pa") is not None else None
        levels.append({
            "label": f"{hpa} hPa" if hpa is not None else "—", "pressure_hpa": hpa,
            "height_m": lv.get("gph_m"), "temp_c": None, "dewpt_c": None,
            "wind_dir": lv.get("wind_dir"), "wind_kt": _mps_to_kt(lv.get("wind_mps")),
        })
    return levels


def _fetch_one_network(net):
    """Registry (elevation) + currents (live obs) for one network -- the two
    independent calls this needs are run concurrently too, not just the
    per-network fan-out in _fetch_stations below."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        registry_f = ex.submit(fetch_network_stations, net)
        currents_f = ex.submit(fetch_network_currents, net)
        registry, currents = registry_f.result(), currents_f.result()
    elev_by_id = {
        f["properties"]["sid"]: f["properties"].get("elevation")
        for f in registry if f.get("properties", {}).get("sid")
    }
    return net, elev_by_id, currents


def _fetch_stations(lat, lon, radius_km, states):
    """Every (state, network) combo is an independent pair of HTTP calls --
    up to 9 combos (3 states x 3 networks) used to run one at a time, a real
    chunk of the old ~20-40s point-query latency. Run them all concurrently."""
    net_codes = build_network_codes(states)
    all_nets = [net for networks in net_codes.values() for net in networks]
    stations_out = []
    seen = set()
    with ThreadPoolExecutor(max_workers=max(1, len(all_nets))) as ex:
        for net, elev_by_id, currents in ex.map(_fetch_one_network, all_nets):
            for obs in currents:
                sid = obs.get("station")
                slat, slon = obs.get("lat"), obs.get("lon")
                # Wind-instrumented stations only -- DCP networks mix in
                # precip/hydro gauges with no wind element at all; those
                # contribute nothing to a fire-weather read and would just
                # show up as unexplained grey markers.
                if not sid or slat is None or slon is None or sid in seen or obs.get("sknt") is None:
                    continue
                dist_km = _haversine_km(lat, lon, slat, slon)
                if dist_km > radius_km:
                    continue
                seen.add(sid)
                sknt, gust = obs.get("sknt"), obs.get("gust")
                elev_m = elev_by_id.get(sid)
                stations_out.append({
                    "id": sid, "name": obs.get("name"), "network": net,
                    "lat": slat, "lon": slon,
                    "elevation_ft": round(elev_m * 3.28084) if elev_m is not None else None,
                    "dist_mi": round(dist_km * 0.621371, 1),
                    "wind_kt": sknt, "wind_mph": _kt_to_mph(sknt),
                    "gust_kt": gust, "gust_mph": _kt_to_mph(gust),
                    "dir_deg": obs.get("drct"),
                    "temp_f": obs.get("tmpf"), "relh_pct": obs.get("relh"),
                    "vis_mi": obs.get("vsby"),
                    "valid_utc": obs.get("utc_valid"),
                })
    return stations_out


def _fetch_snotel(lat, lon, radius_km, states):
    # Per-state station list fetches run concurrently...
    with ThreadPoolExecutor(max_workers=max(1, len(states))) as ex:
        per_state = list(ex.map(fetch_wind_stations, states))

    candidates = []
    seen_triplets = set()
    for st_list in per_state:
        for st in st_list:
            triplet = st.get("stationTriplet")
            slat, slon = st.get("latitude"), st.get("longitude")
            if not triplet or slat is None or slon is None or triplet in seen_triplets:
                continue
            dist_km = _haversine_km(lat, lon, slat, slon)
            if dist_km > radius_km:
                continue
            seen_triplets.add(triplet)
            candidates.append((triplet, st, dist_km))

    # ...and so do the per-station latest-wind lookups -- these used to be
    # one sequential NRCS call per candidate station (often 5-10+ of them).
    snotel_out = []
    if candidates:
        with ThreadPoolExecutor(max_workers=len(candidates)) as ex:
            winds = list(ex.map(lambda c: fetch_latest_wind(c[0]), candidates))
        for (triplet, st, dist_km), wind in zip(candidates, winds):
            if not wind:
                continue  # not currently reporting -- omit, don't show a dead marker
            wspdv = wind.get("WSPDV", {}).get("value")
            wspdx = wind.get("WSPDX", {}).get("value")
            wdirv = wind.get("WDIRV", {}).get("value")
            valid = wind.get("WSPDX", wind.get("WSPDV", {})).get("date")
            snotel_out.append({
                "id": triplet, "name": st.get("name"), "network": st.get("networkCode"),
                "lat": st["latitude"], "lon": st["longitude"], "elevation_ft": st.get("elevation"),
                "dist_mi": round(dist_km * 0.621371, 1),
                "wind_mph": wspdv, "gust_mph": wspdx, "dir_deg": wdirv,
                # Station-local time as returned by the API (each station has
                # its own dataTimeZone in the registry) -- NOT converted to
                # UTC here, so don't compare directly against valid_utc from
                # the IEM stations without accounting for that.
                "valid_local": valid,
            })
    return snotel_out


def _fetch_iteris_cameras(lat, lon, radius_km, states):
    """State DOT RWIS+camera feeds (real coordinates + live camera images,
    see recorder/iteris_rwis.py) -- only fetched for states in
    iteris_rwis.ITERIS_STATES that the query's nearby-states list actually
    touches (currently MT and SD only; other Iteris-platform states are NOT
    verified to share this same feed architecture -- see that module's
    docstring). Kept as its own independent list, not merged into the
    IEM-based *_RWIS stations (no verified ID crosswalk between the two
    systems for any state)."""
    relevant = [s for s in states if s in iteris_rwis.ITERIS_STATES]
    if not relevant:
        return []
    out = []
    with ThreadPoolExecutor(max_workers=len(relevant)) as ex:
        per_state = list(ex.map(iteris_rwis.fetch_rwis, relevant))
    for state_code, features in zip(relevant, per_state):
        for feature in features:
            st = iteris_rwis.parse_station(feature, state_code)
            if st["lat"] is None or st["lon"] is None or not st["cameras"]:
                continue
            dist_km = _haversine_km(lat, lon, st["lat"], st["lon"])
            if dist_km > radius_km:
                continue
            st["dist_mi"] = round(dist_km * 0.621371, 1)
            out.append(st)
    return out


NEXRAD_RADIUS_MI = 100  # the user's explicit ask ("NEXRAD stations within 100 miles
                         # of selection") -- separate from the 75mi ground-sensor
                         # radius and the 300mi sounding radius, a real named
                         # constant like both of those.
NEXRAD_RADIUS_KM = NEXRAD_RADIUS_MI * 1.60934


def _fetch_nexrad(lat, lon, max_km=NEXRAD_RADIUS_KM):
    """Real WSR-88D radar sites within 100mi -- same haversine distance-filter
    pattern as _fetch_iteris_cameras/sites_within above, applied to the live
    IEM Mesonet NEXRAD network registry (see recorder/nexrad_stations.py).
    Reflectivity/velocity imagery itself (national composite mosaic +
    per-station single-site WMS) is wired in client-side in
    dashboard_template.html -- this just returns the real station identity/
    location/distance every marker and popup needs."""
    out = []
    for st in nexrad_stations.fetch_all_stations():
        dist_km = _haversine_km(lat, lon, st["lat"], st["lon"])
        if dist_km > max_km:
            continue
        out.append({**st, "dist_mi": round(dist_km * 0.621371, 1)})
    out.sort(key=lambda s: s["dist_mi"])
    return out


def _fetch_active_fire(lat, lon, radius_km, region):
    """Real live VIIRS + MODIS active-fire detections, from NASA FIRMS'
    official keyless regional CSV feeds (see recorder/firms_active_fire.py)
    -- covers CONUS/Hawaii/Alaska, this project's real scope. No
    state-list dependency, so this can start immediately alongside the
    states lookup rather than waiting on it. Falls back to the global
    Esri/NIFC VIIRS mirror (recorder/viirs_fire.py) for regions with no
    verified NASA keyless feed (territories) -- MODIS has no such fallback
    (no verified global keyless MODIS point source), so it's just [] there,
    a real documented gap rather than a fabricated result."""
    result = firms_active_fire.fetch_active_fire(lat, lon, radius_km, region)
    if firms_active_fire.region_feed_key(region) is None:
        result["viirs"] = viirs_fire.fetch_viirs_hotspots(lat, lon, radius_km)
    return result


def _fetch_one_sounding(site):
    """CONUS-fast path (balloons.py / forecast.weather.gov) first; falls back
    to IGRA (global, but ~1-2 day latency -- see igra.py's module docstring)
    only when the fast path fails. Runs fully independently per site so the
    caller can fan multiple sites out concurrently."""
    entry = {
        "site": site["site"], "name": site["name"],
        "lat": site["lat"], "lon": site["lon"],
        "dist_mi": round(site["distance_km"] * 0.621371, 1),
        "status": "no data", "source": None, "drift_track": None,
    }
    try:
        raw = fetch_latest(site["site"])
        parsed = parse_message(raw["pre"])
        surf = parsed.get("surface")
        lvl700 = parsed.get("70")
        if (surf and surf.get("wind_kt") is not None) or (lvl700 and lvl700.get("wind_kt") is not None):
            entry["status"] = "ok"
            entry["source"] = "NWS MAN product (CONUS, near-immediate)"
            entry["valid_note"] = raw.get("header")
            entry["launch_utc"] = parse_header_launch_time(raw.get("header"))
            if surf and surf.get("wind_kt") is not None:
                entry["surface_wind_mph"] = _kt_to_mph(surf["wind_kt"])
                entry["surface_wind_dir"] = surf.get("wind_dir")
            if lvl700 and lvl700.get("wind_kt") is not None:
                entry["level700_wind_mph"] = _kt_to_mph(lvl700["wind_kt"])
                entry["level700_wind_dir"] = lvl700.get("wind_dir")
            entry["levels"] = _conus_full_profile(parsed)
            reckon_in = drift_track.conus_reckon_input(entry["levels"])
            track = drift_track.dead_reckon(reckon_in, site["lat"], site["lon"])
            if track:
                entry["drift_track"] = track
                # Two stacked assumptions here (standard-atm height where not
                # reported, plus a constant assumed ascent rate) -- flagged
                # more conservatively than IGRA's track below, which has real
                # elapsed time/height inputs even though position is modeled.
                entry["drift_basis"] = "estimated_standard_atmosphere_ascent_rate"
    except Exception as e:
        entry["status"] = f"NWS MAN product failed: {e}"

    if entry["status"] == "ok":
        return entry

    try:
        igra_stations = igra.nearest_active_stations(entry["lat"], entry["lon"], n=1)
        if not igra_stations:
            return entry
        ig = igra_stations[0]
        sounding = igra.fetch_latest_sounding(ig["id"])
        sw = igra.surface_and_700hpa(sounding)
        if sw["surface_wind_mps"] is None and sw["level700_wind_mps"] is None:
            return entry
        entry["status"] = "ok"
        entry["source"] = f"IGRA {ig['id']} (global, ~1-2 day latency, not near-real-time)"
        h = sounding["header"]
        launch_hour = f"{h['hour']:02d}:00" if h["hour"] is not None else "00:00"
        entry["valid_note"] = f"{h['year']}-{h['month']:02d}-{h['day']:02d} {h['hour']:02d}Z" if h["hour"] is not None else f"{h['year']}-{h['month']:02d}-{h['day']:02d}"
        entry["launch_utc"] = f"{h['year']}-{h['month']:02d}-{h['day']:02d}T{launch_hour}:00Z"
        if sw["surface_wind_mps"] is not None:
            entry["surface_wind_mph"] = _mps_to_mph(sw["surface_wind_mps"])
            entry["surface_wind_dir"] = sw["surface_wind_dir"]
        if sw["level700_wind_mps"] is not None:
            entry["level700_wind_mph"] = _mps_to_mph(sw["level700_wind_mps"])
            entry["level700_wind_dir"] = sw["level700_wind_dir"]
        entry["levels"] = _igra_full_profile(sounding)
        reckon_in = drift_track.igra_reckon_input(sounding.get("levels", []))
        track = drift_track.dead_reckon(reckon_in, ig["lat"], ig["lon"])
        if track:
            entry["drift_track"] = track
            # Real elapsed-time + real height inputs (unlike the CONUS path
            # above) -- only the resulting position is modeled, not observed.
            entry["drift_basis"] = "estimated_real_time_and_height"
    except Exception as e:
        entry["status"] = entry["status"] + f"; IGRA also failed: {e}"
    return entry


SOUNDING_RADIUS_MI = 300  # the user's explicit number, asked and confirmed (see
                          # feedback_ask_before_scope_decisions_fireview.md)
                          # after measuring the full-87-station network at a
                          # real 18.6s fetch -- too slow to run on every query.
SOUNDING_RADIUS_KM = SOUNDING_RADIUS_MI * 1.60934


def _fetch_soundings(lat, lon, max_km=SOUNDING_RADIUS_KM, cap=10):
    """All real radiosonde sites within max_km (300 mi) of the queried
    point -- not the full national network (measured too slow: 18.6s for
    all ~87 stations, since this fan-out runs in parallel with, and so sets
    the floor for, the whole query's total latency). `cap` guards against a
    real dense-cluster edge case blowing up fetch count without changing
    the normal-case result (300mi typically returns a handful of real
    sites, not dozens, per the actual US network spacing already checked)."""
    sonde_sites = sites_within(lat, lon, RADIOSONDE_STATIONS, max_km=max_km, cap=cap)
    if not sonde_sites:
        return []
    with ThreadPoolExecutor(max_workers=len(sonde_sites)) as ex:
        return list(ex.map(_fetch_one_sounding, sonde_sites))


def sensors_around_point(lat: float, lon: float, radius_km: float = 120.7008, poo_state: str = None) -> dict:
    """The reusable core: every live sensor within radius_km of an arbitrary
    point, no fire required. Used both by build_snapshot() below (fire-anchored)
    and api_server.py (click-anywhere point queries).
    """
    region = classify_region(poo_state, lat, lon)
    # Soundings don't depend on `states` at all -- start them immediately,
    # in parallel with the states lookup itself, not just with the two
    # branches that do depend on it.
    with ThreadPoolExecutor(max_workers=6) as ex:
        soundings_f = ex.submit(_fetch_soundings, lat, lon)
        active_fire_f = ex.submit(_fetch_active_fire, lat, lon, radius_km, region)
        # NEXRAD doesn't depend on `states` either (the registry fetch is
        # nationwide + cached, see nexrad_stations.py) -- start it immediately
        # alongside soundings/active-fire rather than waiting on the states
        # lookup like the two branches below do.
        nexrad_f = ex.submit(_fetch_nexrad, lat, lon)
        states = nearby_states(lat, lon, radius_km)
        stations_f = ex.submit(_fetch_stations, lat, lon, radius_km, states)
        snotel_f = ex.submit(_fetch_snotel, lat, lon, radius_km, states)
        cameras_f = ex.submit(_fetch_iteris_cameras, lat, lon, radius_km, states)
        stations, snotel, soundings, cameras, active_fire, nexrad = (
            stations_f.result(), snotel_f.result(), soundings_f.result(), cameras_f.result(),
            active_fire_f.result(), nexrad_f.result()
        )
    return {
        "point": {"lat": lat, "lon": lon, "region": region, "radius_mi": round(radius_km * 0.621371)},
        "stations": stations,
        "snotel": snotel,
        "soundings": soundings,
        "cameras": cameras,
        "viirs": active_fire["viirs"],
        "modis": active_fire["modis"],
        "nexrad": nexrad,
    }


def build_snapshot(fire_name: str, radius_km: float = 120.7008) -> dict:  # 120.7008 km = exactly 75 mi
    fire = resolve_fire(fire_name)
    lat, lon = fire["lat"], fire["lon"]
    fire_id = fire.get("UniqueFireIdentifier") or _slug(fire["IncidentName"])

    core = sensors_around_point(lat, lon, radius_km, fire.get("POOState"))

    perimeter = fetch_perimeter(fire["IncidentName"])
    perimeter_out = None
    if perimeter is not None:
        # Leaflet wants [lat,lon]; WFIGS rings are [lon,lat]. Decimate only if
        # very large -- keeps real shape fidelity, just caps payload size.
        rings_latlon = []
        for ring in perimeter["rings"]:
            step = max(1, round(len(ring) / 400))
            pts = [[p[1], p[0]] for p in ring[::step]]
            rings_latlon.append(pts)
        perimeter_out = {
            "rings": rings_latlon,
            "acres": perimeter["acres"],
            "source": perimeter["source"],
            "fire_behavior_general": perimeter["fire_behavior_general"],
            "percent_contained": perimeter["percent_contained"],
        }

    return {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fire": {
            "fire_id": fire_id,
            "name": fire["IncidentName"],
            "state": fire.get("POOState"),
            "region": core["point"]["region"],
            "lat": lat, "lon": lon,
            "acres": fire.get("IncidentSize"),
            "percent_contained": fire.get("PercentContained"),
            "personnel": fire.get("TotalIncidentPersonnel"),
            "radius_mi": core["point"]["radius_mi"],
        },
        "perimeter": perimeter_out,
        "stations": core["stations"],
        "snotel": core["snotel"],
        "soundings": core["soundings"],
        "cameras": core["cameras"],
        "viirs": core["viirs"],
        "modis": core["modis"],
        "nexrad": core["nexrad"],
    }


def main():
    fire_name = sys.argv[1] if len(sys.argv) > 1 else "Silvertip"
    radius_km = float(sys.argv[2]) if len(sys.argv) > 2 else 120.7008  # exactly 75 mi

    try:
        snapshot = build_snapshot(fire_name, radius_km)
    except AmbiguousFireError as e:
        print("AMBIGUOUS:", e)
        sys.exit(1)
    except FireResolutionError as e:
        print("ERROR:", e)
        sys.exit(1)

    fire_id = snapshot["fire"]["fire_id"]
    out_dir = Path(__file__).parent / "fires" / _slug(fire_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sensor_snapshot.json").write_text(json.dumps(snapshot, indent=2))
    (out_dir / "config.json").write_text(json.dumps({
        "fire_name": snapshot["fire"]["name"],
        "fire_id": fire_id,
        "radius_km": radius_km,
        "region": snapshot["fire"]["region"],
    }, indent=2))

    # Static copy of the shared template, not a symlink -- re-copy every
    # build so per-fire dashboards stay in sync with template edits.
    template = Path(__file__).parent / "dashboard_template.html"
    if template.exists():
        shutil.copy(template, out_dir / "dashboard.html")

    print(f"{snapshot['fire']['name']}: {len(snapshot['stations'])} stations, "
          f"{len(snapshot['snotel'])} SNOTEL, {len(snapshot['soundings'])} radiosonde sites "
          f"-> {out_dir}\\sensor_snapshot.json")
    print(f"Dashboard: {out_dir}\\dashboard.html (serve this folder over HTTP, don't open via file://)")


if __name__ == "__main__":
    main()
