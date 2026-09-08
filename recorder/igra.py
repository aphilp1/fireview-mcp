#!/usr/bin/env python3
"""
NOAA/NCEI Integrated Global Radiosonde Archive (IGRA v2.2) -- global radiosonde
coverage (CONUS, Alaska, Hawaii, territories, and internationally), fixing the
real gap balloons.py has outside CONUS (forecast.weather.gov's MAN-product
mechanism only works for the Lower 48). Real tradeoff, stated plainly: IGRA's
own docs say "near real time... within two calendar days" -- this is
day-old-to-two-days-old data, not the near-immediate CONUS feed. Use balloons.py
first where it works; fall back to this everywhere it doesn't.

No fabrication: IGRA's sounding format has NO per-level lat/lon (confirmed
against the official format doc -- LAT/LON are header-only, fixed per station).
compute_drift_track() below is therefore an ESTIMATED dead-reckoning track
built from each level's wind speed/direction and elapsed time since release,
not an observed GPS path -- every consumer of it must label it as modeled.
"""
import datetime
import io
import re
import zipfile

import requests

STATION_LIST_URL = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/doc/igra2-station-list.txt"
DATA_Y2D_BASE = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/access/data-y2d"

EARTH_RADIUS_KM = 6371.0
_station_list_cache = None


def _haversine_km(lat1, lon1, lat2, lon2):
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def fetch_station_list(force=False) -> list:
    """All ~2900 IGRA stations worldwide. Cached in-process (this file is
    static enough day-to-day that re-fetching per lookup would be wasteful) --
    pass force=True to bypass the cache. FIXED-WIDTH columns, verified against
    the live file (a plain 2+-space regex split first attempt silently broke
    on single-space-separated FIRSTYEAR/LASTYEAR and returned zero stations --
    caught by testing the parser standalone before trusting it, not assumed):
    ID 1-11, LAT 13-20, LON 22-30, ELEV 32-37, STATE 39-40, NAME 42-71,
    FIRSTYEAR 73-76, LASTYEAR 78-81.
    """
    global _station_list_cache
    if _station_list_cache is not None and not force:
        return _station_list_cache
    try:
        r = requests.get(STATION_LIST_URL, timeout=30)
        r.raise_for_status()
        text = r.text
    except Exception:
        return []

    stations = []
    for line in text.splitlines():
        if len(line) < 81:
            continue
        try:
            sid = line[0:11].strip()
            lat = float(line[12:20])
            lon = float(line[21:30])
            elev_m = float(line[31:37])
            name = line[41:71].strip()
            first_year = int(line[72:76])
            last_year = int(line[77:81])
        except (ValueError, IndexError):
            continue
        stations.append({
            "id": sid, "lat": lat, "lon": lon,
            "elevation_m": elev_m if elev_m > -999 else None,
            "name": name, "first_year": first_year, "last_year": last_year,
        })
    _station_list_cache = stations
    return stations


def nearest_active_stations(lat: float, lon: float, n: int = 2, max_age_years: int = 2) -> list:
    """Nearest N stations with real recent data (last_year within
    max_age_years of the current year) -- excludes the many historical-only
    IGRA stations that would otherwise silently win a pure-distance search
    and return nothing live. Each result gets a 'distance_km' field.
    """
    stations = fetch_station_list()
    if not stations:
        return []
    current_year = datetime.datetime.now(datetime.timezone.utc).year
    active = [s for s in stations if s["last_year"] >= current_year - max_age_years]
    for s in active:
        s["distance_km"] = _haversine_km(lat, lon, s["lat"], s["lon"])
    active.sort(key=lambda s: s["distance_km"])
    return active[:n]


def fetch_latest_sounding(station_id: str) -> dict:
    """Fetches the year-to-date file for one station and parses the LAST
    (most recent) sounding in it. Returns {'header': {...}, 'levels': [...]}
    or raises on failure -- caller decides how to report "no data" (matches
    balloons.py's NoSoundingFoundError-style contract, but this one carries
    the real exception rather than a custom type since failure modes here are
    more varied: 404 for a station with no y2d file, network error, empty file).
    """
    url = f"{DATA_Y2D_BASE}/{station_id}-data-beg{datetime.datetime.now(datetime.timezone.utc).year}.txt.zip"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        inner_name = zf.namelist()[0]
        text = zf.read(inner_name).decode("ascii", errors="replace")

    lines = text.splitlines()
    header_idx = [i for i, l in enumerate(lines) if l.startswith("#")]
    if not header_idx:
        raise ValueError(f"No header records found in {station_id}'s y2d file")

    last_h = header_idx[-1]
    hline = lines[last_h]
    header = {
        "id": hline[1:12].strip(),
        "year": int(hline[13:17]), "month": int(hline[18:20]), "day": int(hline[21:23]),
        "hour": int(hline[24:26]) if hline[24:26].strip() != "99" else None,
        "reltime": hline[27:31].strip(),
        "numlev": int(hline[32:36]),
    }
    end = header_idx[-1] + 1 + header["numlev"]
    levels = []
    for l in lines[last_h + 1:end]:
        try:
            etime = int(l[3:8])
            press = int(l[9:15])   # Pa; -9999/-8888 = missing
            gph = int(l[16:21])    # m
            wdir = int(l[40:45])   # degrees
            wspd = int(l[46:51])   # tenths of m/s
        except (ValueError, IndexError):
            continue
        levels.append({
            "etime_s": etime if etime not in (-9999, -8888) else None,
            "pressure_pa": press if press not in (-9999, -8888) else None,
            "gph_m": gph if gph not in (-9999, -8888) else None,
            "wind_dir": wdir if wdir not in (-9999, -8888) else None,
            "wind_mps": wspd / 10.0 if wspd not in (-9999, -8888) else None,
        })
    return {"header": header, "levels": levels}


def surface_and_700hpa(sounding: dict) -> dict:
    """Pulls the surface (lowest valid level) and 700 hPa (70000 Pa, nearest
    match within 2000 Pa) wind from a parsed sounding. Returns {} fields as
    None where genuinely absent, never guessed."""
    levels = [lv for lv in sounding["levels"] if lv["wind_mps"] is not None]
    out = {"surface_wind_mps": None, "surface_wind_dir": None,
           "level700_wind_mps": None, "level700_wind_dir": None}
    if not levels:
        return out
    surf = min(levels, key=lambda lv: lv["etime_s"] if lv["etime_s"] is not None else 0)
    out["surface_wind_mps"] = surf["wind_mps"]
    out["surface_wind_dir"] = surf["wind_dir"]
    candidates = [lv for lv in levels if lv["pressure_pa"] is not None and abs(lv["pressure_pa"] - 70000) <= 2000]
    if candidates:
        lvl700 = min(candidates, key=lambda lv: abs(lv["pressure_pa"] - 70000))
        out["level700_wind_mps"] = lvl700["wind_mps"]
        out["level700_wind_dir"] = lvl700["wind_dir"]
    return out


def compute_drift_track(sounding: dict, launch_lat: float, launch_lon: float) -> list:
    """ESTIMATED balloon drift path via dead reckoning: at each level, moves
    the running position by wind_speed * dt in the direction the wind is
    blowing TOWARD (wind_dir + 180, since WDIR is the meteorological
    'from' direction). This is a modeled trajectory, not an observed one --
    IGRA has no per-level GPS position (confirmed against the format spec).
    Returns [] if there's not enough data (fewer than 2 usable levels) to
    integrate anything meaningful.
    """
    import math
    levels = sorted(
        [lv for lv in sounding["levels"] if lv["etime_s"] is not None and lv["wind_mps"] is not None and lv["wind_dir"] is not None and lv["wind_dir"] <= 360],
        key=lambda lv: lv["etime_s"],
    )
    if len(levels) < 2:
        return []
    track = [{"lat": launch_lat, "lon": launch_lon, "etime_s": levels[0]["etime_s"], "gph_m": levels[0].get("gph_m")}]
    lat, lon = launch_lat, launch_lon
    for prev, cur in zip(levels, levels[1:]):
        dt = cur["etime_s"] - prev["etime_s"]
        if dt <= 0 or dt > 1800:  # skip bad/huge gaps rather than fabricate a jump
            continue
        toward_deg = (cur["wind_dir"] + 180) % 360
        dist_km = (cur["wind_mps"] * dt) / 1000.0
        brg = math.radians(toward_deg)
        lat1, lon1 = math.radians(lat), math.radians(lon)
        d_r = dist_km / EARTH_RADIUS_KM
        lat2 = math.asin(math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brg))
        lon2 = lon1 + math.atan2(math.sin(brg) * math.sin(d_r) * math.cos(lat1), math.cos(d_r) - math.sin(lat1) * math.sin(lat2))
        lat, lon = math.degrees(lat2), math.degrees(lon2)
        track.append({"lat": lat, "lon": lon, "etime_s": cur["etime_s"], "gph_m": cur.get("gph_m")})
    return track


if __name__ == "__main__":
    import json
    import sys
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 64.27
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else -148.35
    stations = nearest_active_stations(lat, lon, n=2)
    for s in stations:
        print(f"{s['id']} {s['name']} {s['distance_km']:.1f} km, active {s['first_year']}-{s['last_year']}")
    if stations:
        sid = stations[0]["id"]
        sounding = fetch_latest_sounding(sid)
        print(f"\n{sid} header: {sounding['header']}, {len(sounding['levels'])} levels")
        print("surface/700hPa:", json.dumps(surface_and_700hpa(sounding), indent=2))
        track = compute_drift_track(sounding, stations[0]["lat"], stations[0]["lon"])
        print(f"drift track: {len(track)} points, first={track[0] if track else None}, last={track[-1] if track else None}")
