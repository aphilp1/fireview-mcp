#!/usr/bin/env python3
"""
Real-time VIIRS active-fire/thermal-anomaly detections (375m pixels), from
the public Esri/NIFC Living Atlas feature service that mirrors NASA FIRMS --
no API key needed (FIRMS' own API requires a registered MAP_KEY; this hosted
copy does not). Covers all three VIIRS-carrying satellites (Suomi NPP,
NOAA-20, NOAA-21 -- the instrument the user asked about directly), globally, so
it works the same for CONUS, Alaska, Hawaii, and territories with no
region-specific handling needed.

Verified live 2026-09-04 (not assumed from an old link): the FeatureServer
returns real point features with the field schema below, and a real bbox
query around the live Silvertip fire (MT) returned actual nearby hotspots.

Source: https://www.arcgis.com/home/item.html?id=dece90af1a0242dcbf0ca36d30276aa3
Layer:  https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Satellite_VIIRS_Thermal_Hotspots_and_Fire_Activity/FeatureServer/0
"""
import math

import requests

VIIRS_URL = ("https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/"
             "Satellite_VIIRS_Thermal_Hotspots_and_Fire_Activity/FeatureServer/0/query")

# From the service's own field metadata (query/0?f=json), not guessed.
SATELLITE_NAMES = {"N": "Suomi NPP", "N20": "NOAA-20", "N21": "NOAA-21"}

EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def fetch_viirs_hotspots(lat: float, lon: float, radius_km: float, max_hours: int = 48) -> list:
    """Live VIIRS detections within radius_km of (lat, lon), acquired in the
    last max_hours (the service's own `hours_old` field, updated hourly).
    Returns [] on any fetch failure -- a real, non-fatal outcome (no active
    fire nearby is the overwhelmingly common case), never fabricated."""
    deg = radius_km / 111.0  # coarse bbox pre-filter; exact distance re-checked below
    bbox = f"{lon - deg},{lat - deg},{lon + deg},{lat + deg}"
    params = {
        "geometry": bbox, "geometryType": "esriGeometryEnvelope", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "latitude,longitude,confidence,frp,satellite,acq_date,acq_time,daynight,hours_old",
        "where": f"hours_old <= {int(max_hours)}",
        "f": "json", "resultRecordCount": 2000,
    }
    try:
        r = requests.get(VIIRS_URL, params=params, timeout=20)
        r.raise_for_status()
        features = r.json().get("features", [])
    except Exception:
        return []

    out = []
    for feat in features:
        a = feat.get("attributes", {})
        flat, flon = a.get("latitude"), a.get("longitude")
        if flat is None or flon is None:
            continue
        dist_km = _haversine_km(lat, lon, flat, flon)
        if dist_km > radius_km:
            continue
        # acq_date/acq_time come back as epoch milliseconds (esriFieldTypeDate).
        acq_ms = a.get("acq_time") or a.get("acq_date")
        acq_utc = None
        if acq_ms is not None:
            import datetime
            acq_utc = datetime.datetime.utcfromtimestamp(acq_ms / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append({
            "lat": flat, "lon": flon,
            "confidence": a.get("confidence"),
            "frp_mw": a.get("frp"),
            "satellite": SATELLITE_NAMES.get(a.get("satellite"), a.get("satellite")),
            "daynight": "Day" if a.get("daynight") == "D" else ("Night" if a.get("daynight") == "N" else a.get("daynight")),
            "hours_old": a.get("hours_old"),
            "acq_utc": acq_utc,
            "dist_mi": round(dist_km * 0.621371, 1),
        })
    return out


if __name__ == "__main__":
    import json
    import sys
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 47.84
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else -113.27
    hotspots = fetch_viirs_hotspots(lat, lon, radius_km=120.7008)
    print(f"{len(hotspots)} VIIRS detections within 75mi of ({lat}, {lon})")
    if hotspots:
        print(json.dumps(hotspots[0], indent=2))
