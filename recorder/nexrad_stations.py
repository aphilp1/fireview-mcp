#!/usr/bin/env python3
"""
Real WSR-88D NEXRAD radar site registry -- a live IEM Mesonet network feed,
not a hardcoded list (site counts do change: Guam's radar, decommissions,
etc.). Verified live 2026-09-05: 160 real stations returned, spot-checked
site elevations against known real values (KFTG Denver/Boulder 1677.45m
register vs ~1677m real; KTLX Oklahoma City 368.0m vs ~368m real -- this
feed's `elevation` field is meters, confirmed by that match).

Source: https://mesonet.agron.iastate.edu/geojson/network.php?network=NEXRAD
-- the "NEXRAD" IEM Mesonet network, same provider this project already
uses for ASOS/RWIS/DCP (see stations.py). The feed's `sid` is the 3-letter
site id WITHOUT the K/P/T ICAO prefix (e.g. "TLX", not "KTLX") -- _icao_id()
below derives the real 4-letter id needed for the NOAA single-site radar
imagery (opengeo.ncep.noaa.gov WMS, wired in from build_sensor_snapshot.py)
from each station's real `state` field: K for CONUS, P for Alaska/Hawaii/
Guam/American Samoa/N.Mariana Is., T for Puerto Rico/US Virgin Islands --
the only non-K cases NWS actually uses. Three overseas military sites in
this feed carry a blank state (Kunsan AB and Camp Humphreys, South Korea;
Kadena AB, Okinawa) and fall through to the K-prefix default here, which is
wrong for those three specifically -- left unfixed since it's functionally
moot: no real US query point is ever within 100mi of them, so they never
reach a rendered marker via _fetch_nexrad()'s distance filter.

GetMap image bbox convention (used by the dashboard for per-station
reflectivity/velocity imagery): verified live against three real stations'
own WMS GetCapabilities responses (KTLX, KFTG, PAKC) that NOAA's
`<sid>_sr_bref`/`<sid>_sr_bvel` layers all use a station-centered
lon-5..lon+5, lat-5..lat+5 LatLonBoundingBox -- not assumed, checked because
this module's real lat/lon is what that box gets built from.
"""
import time

import requests

STATIONS_URL = "https://mesonet.agron.iastate.edu/geojson/network.php?network=NEXRAD"
CACHE_TTL_S = 24 * 3600  # the real site list changes on the order of years, not per-query

_cache = {"fetched_at": 0, "data": []}

_ICAO_PREFIX_BY_STATE = {"AK": "P", "HI": "P", "GU": "P", "AS": "P", "MP": "P", "PR": "T", "VI": "T"}


def _icao_id(sid: str, state: str) -> str:
    return _ICAO_PREFIX_BY_STATE.get((state or "").strip(), "K") + sid


def fetch_all_stations(force: bool = False) -> list:
    """Every real NEXRAD site IEM currently tracks: id (4-letter ICAO),
    short_id (IEM's 3-letter sid), name, state, lat, lon, elevation_ft.
    A feature missing usable coordinates is skipped, never guessed. Returns
    the last good cached list (possibly empty on a cold start) if the live
    fetch itself fails -- a transient outage here shouldn't take down every
    other layer in the same query."""
    now = time.time()
    if not force and _cache["data"] and (now - _cache["fetched_at"]) < CACHE_TTL_S:
        return _cache["data"]
    try:
        r = requests.get(STATIONS_URL, timeout=20)
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception:
        return _cache["data"]
    out = []
    for f in feats:
        props = f.get("properties", {})
        sid = props.get("sid")
        coords = (f.get("geometry") or {}).get("coordinates")
        if not sid or not coords or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        if lat is None or lon is None:
            continue
        elev_m = props.get("elevation")
        state = (props.get("state") or "").strip() or None
        out.append({
            "id": _icao_id(sid, state), "short_id": sid,
            "name": props.get("sname"), "state": state,
            "lat": lat, "lon": lon,
            "elevation_ft": round(elev_m * 3.28084) if elev_m is not None else None,
        })
    if out:
        _cache["data"] = out
        _cache["fetched_at"] = now
    return _cache["data"]


if __name__ == "__main__":
    import json
    stations = fetch_all_stations(force=True)
    print(f"{len(stations)} real NEXRAD stations")
    print(json.dumps(stations[:3], indent=2))
