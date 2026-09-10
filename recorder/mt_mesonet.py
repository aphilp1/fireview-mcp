#!/usr/bin/env python3
"""
Montana Mesonet v2 -- the state's own network (231 stations live-confirmed
2026-09-10, vs. the ~216 the Earth_Data_Sourcebook.pdf survey found), richer
and more current than what FireView-MCP already gets for Montana via IEM's
older MT_ASOS/MT_RWIS/MT_DCP feed. Free, keyless REST API
(mesonet.climate.umt.edu/api/v2), documented as the best public API found
across the ~50 state mesonets surveyed in that document.

Deliberately a SEPARATE network ("MTMESO"), not merged into the existing
IEM-based Montana stations -- no verified station-id crosswalk between the
two systems, so name/proximity-matching them would risk fabricating false
pairings (same reasoning already applied to iteris_rwis.py's MDT cameras
vs. IEM's MT_RWIS).
"""
import datetime
import math

import requests

STATIONS_URL = "https://mesonet.climate.umt.edu/api/v2/stations/?type=json"
LATEST_URL = "https://mesonet.climate.umt.edu/api/v2/latest/?type=json"
EARTH_RADIUS_MI = 3958.8

_stations_cache = None


def _haversine_mi(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(a))


def fetch_stations(force: bool = False) -> list:
    """All active station metadata. Cached in-process (this list changes
    rarely day to day) -- pass force=True to bypass."""
    global _stations_cache
    if _stations_cache is not None and not force:
        return _stations_cache
    r = requests.get(STATIONS_URL, timeout=30)
    r.raise_for_status()
    _stations_cache = r.json()
    return _stations_cache


def fetch_latest() -> dict:
    """The most recent (updated ~every 5 min) observation for every
    station, keyed by station code."""
    r = requests.get(LATEST_URL, timeout=30)
    r.raise_for_status()
    return {row["station"]: row for row in r.json()}


def _first(obs, *keys):
    for k in keys:
        v = obs.get(k)
        if v is not None:
            return v
    return None


def fetch_wind_stations_nearby(lat: float, lon: float, radius_mi: float) -> list:
    """Real, live, wind-instrumented Montana Mesonet stations within
    radius_mi -- most HydroMet sites report at a 10m mast, a few shorter
    ones only at 8ft, so both are checked rather than assuming one mast
    height universally. A station with neither is skipped, matching this
    project's wind-instrumented-only convention everywhere else."""
    stations = fetch_stations()
    latest = fetch_latest()
    out = []
    for st in stations:
        obs = latest.get(st["station"])
        if not obs:
            continue
        wind = _first(obs, "Wind Speed @ 10 m [mi/h]", "Wind Speed @ 8 ft [mi/h]")
        if wind is None:
            continue
        dist_mi = _haversine_mi(lat, lon, st["latitude"], st["longitude"])
        if dist_mi > radius_mi:
            continue
        dt_ms = obs.get("datetime")
        valid_utc = None
        if dt_ms:
            valid_utc = datetime.datetime.fromtimestamp(
                dt_ms / 1000, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        elev_m = st.get("elevation")
        out.append({
            "id": st["station"], "name": st["name"], "network": "MTMESO",
            "lat": st["latitude"], "lon": st["longitude"],
            "elevation_ft": round(elev_m * 3.28084) if elev_m is not None else None,
            "dist_mi": round(dist_mi, 1),
            "wind_mph": round(wind, 1),
            "gust_mph": _first(obs, "Gust Speed @ 10 m [mi/h]", "Gust Speed @ 8 ft [mi/h]"),
            "dir_deg": _first(obs, "Wind Direction @ 10 m [deg]", "Wind Direction @ 8 ft [deg]"),
            "temp_f": _first(obs, "Air Temperature @ 2 m [°F]", "Air Temperature @ 8 ft [°F]"),
            "relh_pct": obs.get("Relative Humidity [%]"),
            "valid_utc": valid_utc,
        })
    return out


if __name__ == "__main__":
    import json
    import sys
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 47.34
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else -114.08
    stations = fetch_wind_stations_nearby(lat, lon, 75)
    print(f"{len(stations)} wind-instrumented Montana Mesonet stations within 75mi")
    for s in stations[:5]:
        print(" ", json.dumps(s))
