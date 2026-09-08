#!/usr/bin/env python3
"""
Real-time active-fire detections -- VIIRS (375m: Suomi NPP, NOAA-20, NOAA-21)
and MODIS (1km: Terra+Aqua) -- from NASA FIRMS' own free, no-API-key NRT CSV
feeds. Same real source and technique already proven in the FireEstimator
project's scripts/pull_firms.py (that project also documents the real reason
MODIS's wider off-nadir pixel footprint isn't used for acreage/area math --
irrelevant here, FireView only plots detection points, no polygon union).

Regional feeds only, not the Global one -- verified live 2026-09-04 that the
Global VIIRS feed alone is ~13.6MB/167k rows (one satellite), far too slow
for a per-query fetch. The regional feeds are small (CONUS+HI VIIRS ~200KB)
and fast (<1s). Two regions verified to exist as named keyless feeds:
"USA_contiguous_and_Hawaii" and "Alaska" -- covers this project's real
scope (region.py's CONUS/Alaska/Hawaii). No verified keyless regional feed
exists for US territories (Puerto Rico/Guam/etc. all 404 by the same naming
pattern) -- callers should fall back to recorder/viirs_fire.py's global Esri
mirror for those (VIIRS only; no verified global keyless MODIS point source).

VIIRS and MODIS use genuinely different CSV schemas (confirmed live, not
assumed): VIIRS carries bright_ti4/bright_ti5 and a low/nominal/high
confidence string; MODIS carries brightness/bright_t31 and a 0-100 numeric
confidence. parse_row() below keeps both, never guesses one from the other.
"""
import csv
import io
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire"

REGIONAL_FEEDS = {
    "conus_hi": {
        "VIIRS_SNPP":   f"{FIRMS_BASE}/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_USA_contiguous_and_Hawaii_24h.csv",
        "VIIRS_NOAA20": f"{FIRMS_BASE}/noaa-20-viirs-c2/csv/J1_VIIRS_C2_USA_contiguous_and_Hawaii_24h.csv",
        "VIIRS_NOAA21": f"{FIRMS_BASE}/noaa-21-viirs-c2/csv/J2_VIIRS_C2_USA_contiguous_and_Hawaii_24h.csv",
        "MODIS":        f"{FIRMS_BASE}/modis-c6.1/csv/MODIS_C6_1_USA_contiguous_and_Hawaii_24h.csv",
    },
    "alaska": {
        "VIIRS_SNPP":   f"{FIRMS_BASE}/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Alaska_24h.csv",
        "VIIRS_NOAA20": f"{FIRMS_BASE}/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Alaska_24h.csv",
        "VIIRS_NOAA21": f"{FIRMS_BASE}/noaa-21-viirs-c2/csv/J2_VIIRS_C2_Alaska_24h.csv",
        "MODIS":        f"{FIRMS_BASE}/modis-c6.1/csv/MODIS_C6_1_Alaska_24h.csv",
    },
}
VIIRS_SATELLITE_NAMES = {"VIIRS_SNPP": "Suomi NPP", "VIIRS_NOAA20": "NOAA-20", "VIIRS_NOAA21": "NOAA-21"}

UA = {"User-Agent": "FireView-MCP/1.0 (personal research project)"}
EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def region_feed_key(region: str):
    """None means no verified keyless regional feed for this region -- caller
    should fall back elsewhere (see module docstring), not fabricate one."""
    if region == "Alaska":
        return "alaska"
    if region in ("CONUS", "Hawaii"):
        return "conus_hi"
    return None


def _fetch_csv(url):
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        return list(csv.DictReader(io.StringIO(r.text)))
    except Exception:
        return []


def _acq_utc(rec):
    try:
        t = rec["acq_time"].zfill(4)
        dt = datetime.strptime(f'{rec["acq_date"]} {t[:2]}:{t[2:]}', "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except (KeyError, ValueError):
        return None, None


def _parse_viirs_row(rec, sensor_key, lat, lon, radius_km):
    try:
        rlat, rlon = float(rec["latitude"]), float(rec["longitude"])
    except (KeyError, ValueError):
        return None
    dist_km = _haversine_km(lat, lon, rlat, rlon)
    if dist_km > radius_km:
        return None
    acq_utc, hours_old = _acq_utc(rec)
    return {
        "lat": rlat, "lon": rlon,
        "confidence": rec.get("confidence"),
        "frp_mw": float(rec["frp"]) if rec.get("frp") else None,
        "satellite": VIIRS_SATELLITE_NAMES.get(sensor_key, sensor_key),
        "daynight": "Day" if rec.get("daynight") == "D" else ("Night" if rec.get("daynight") == "N" else rec.get("daynight")),
        "hours_old": round(hours_old, 1) if hours_old is not None else None,
        "acq_utc": acq_utc,
        "dist_mi": round(dist_km * 0.621371, 1),
    }


def _parse_modis_row(rec, lat, lon, radius_km):
    try:
        rlat, rlon = float(rec["latitude"]), float(rec["longitude"])
    except (KeyError, ValueError):
        return None
    dist_km = _haversine_km(lat, lon, rlat, rlon)
    if dist_km > radius_km:
        return None
    acq_utc, hours_old = _acq_utc(rec)
    return {
        "lat": rlat, "lon": rlon,
        "confidence_pct": int(rec["confidence"]) if rec.get("confidence", "").isdigit() else None,
        "frp_mw": float(rec["frp"]) if rec.get("frp") else None,
        "brightness_k": float(rec["brightness"]) if rec.get("brightness") else None,
        "satellite": {"T": "Terra", "A": "Aqua"}.get(rec.get("satellite"), rec.get("satellite")),
        "daynight": "Day" if rec.get("daynight") == "D" else ("Night" if rec.get("daynight") == "N" else rec.get("daynight")),
        "hours_old": round(hours_old, 1) if hours_old is not None else None,
        "acq_utc": acq_utc,
        "dist_mi": round(dist_km * 0.621371, 1),
    }


def fetch_active_fire(lat: float, lon: float, radius_km: float, region: str) -> dict:
    """Real VIIRS + MODIS detections within radius_km of (lat, lon), for
    whichever of NASA FIRMS' two relevant keyless regional feeds covers
    `region`. Returns {"viirs": [...], "modis": [...]}, both [] (not an
    error) when region has no verified feed here -- see module docstring."""
    key = region_feed_key(region)
    if key is None:
        return {"viirs": [], "modis": []}
    feeds = REGIONAL_FEEDS[key]
    sensor_keys = list(feeds.keys())
    with ThreadPoolExecutor(max_workers=len(sensor_keys)) as ex:
        raw = dict(zip(sensor_keys, ex.map(_fetch_csv, feeds.values())))

    viirs, modis = [], []
    for sensor_key in ("VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21"):
        for rec in raw.get(sensor_key, []):
            parsed = _parse_viirs_row(rec, sensor_key, lat, lon, radius_km)
            if parsed:
                viirs.append(parsed)
    for rec in raw.get("MODIS", []):
        parsed = _parse_modis_row(rec, lat, lon, radius_km)
        if parsed:
            modis.append(parsed)
    return {"viirs": viirs, "modis": modis}


if __name__ == "__main__":
    import json
    import sys
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 47.84
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else -113.27
    region = sys.argv[3] if len(sys.argv) > 3 else "CONUS"
    result = fetch_active_fire(lat, lon, radius_km=120.7008, region=region)
    print(f"{len(result['viirs'])} VIIRS, {len(result['modis'])} MODIS within 75mi of ({lat}, {lon}), region={region}")
    if result["viirs"]:
        print("VIIRS sample:", json.dumps(result["viirs"][0], indent=2))
    if result["modis"]:
        print("MODIS sample:", json.dumps(result["modis"][0], indent=2))
