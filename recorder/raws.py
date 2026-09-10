#!/usr/bin/env python3
"""
Real-time RAWS (Remote Automated Weather Station) observations -- the
USFS/BLM/NPS/FWS/BIA fire-weather network coordinated under NIFC, ~2,200-
3,220 stations nationwide (source count genuinely inconsistent across NIFC/
WRCC, per Earth_Data_Sourcebook.pdf). Purpose-built for fire weather (every
station reports fuel temperature/moisture alongside standard met), so this
is a direct fit for FireView-MCP's use case, not a generic add-on.

Source: NIFC's own public "PublicView_RAWS" ArcGIS FeatureServer (found via
data-nifc.opendata.arcgis.com's DCAT feed, not guessed) -- free, keyless,
supports a native geometry+distance query so no separate state/bbox lookup
is needed the way IEM's per-state networks require.

Real quirks found live, not assumed: every numeric field is returned as a
unit-suffixed STRING ("18 mph", "217 degrees ", "62 deg. F") or the literal
sentinel "NO DATA" for a station not currently reporting that element --
both handled explicitly by _num() below. FuelMoisture/FuelTemp are commonly
"NO DATA" even on otherwise-reporting stations (not every RAWS unit carries
a fuel stick) -- left as None, never guessed. ObservedDate can be null or
genuinely very old (a portable station not currently deployed) -- callers
should treat a large age as a real "not currently reporting" state, same
convention as this project's other sources' staleness handling.
"""
import re
import datetime
import requests

RAWS_URL = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/PublicView_RAWS/FeatureServer/1/query"

OUT_FIELDS = (
    "StationName,StationID,Latitude,Longitude,WindSpeedMPH,WindDirDegrees,"
    "WindSpeedPeak,AirTempStandPlace,RelativeHumidity,FuelMoisture,FuelTemp,"
    "ObservedDate,Agency,Elevation"
)


def _num(v):
    """Strips a unit suffix off a RAWS value string ("18 mph" -> 18.0);
    returns None for null/empty/"NO DATA" rather than guessing a value."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.upper() == "NO DATA":
        return None
    m = re.search(r"-?\d+\.?\d*", s)
    return float(m.group()) if m else None


def fetch_nearby(lat: float, lon: float, radius_mi: float) -> list:
    """Real live RAWS stations within radius_mi of (lat, lon), wind-
    instrumented only (a station with no current wind reading contributes
    nothing to a fire-weather read, same filtering convention as this
    project's other sources). Each result: id/name/network/lat/lon/
    elevation_ft/wind_mph/gust_mph/dir_deg/temp_f/relh_pct/
    fuel_moisture_pct/fuel_temp_f/agency/valid_utc."""
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "distance": radius_mi, "units": "esriSRUnit_StatuteMile",
        "outFields": OUT_FIELDS, "returnGeometry": "false", "f": "json",
    }
    r = requests.get(RAWS_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    out = []
    for feat in data.get("features", []):
        a = feat.get("attributes", {})
        wind = _num(a.get("WindSpeedMPH"))
        if wind is None:
            continue
        obs_ms = a.get("ObservedDate")
        valid_utc = None
        if obs_ms:
            valid_utc = datetime.datetime.fromtimestamp(
                obs_ms / 1000, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append({
            "id": a.get("StationID") or a.get("StationName"),
            "name": a.get("StationName"),
            "network": "RAWS",
            "lat": a.get("Latitude"), "lon": a.get("Longitude"),
            "elevation_ft": a.get("Elevation"),
            "wind_mph": wind,
            "gust_mph": _num(a.get("WindSpeedPeak")),
            "dir_deg": _num(a.get("WindDirDegrees")),
            "temp_f": _num(a.get("AirTempStandPlace")),
            "relh_pct": _num(a.get("RelativeHumidity")),
            "fuel_moisture_pct": _num(a.get("FuelMoisture")),
            "fuel_temp_f": _num(a.get("FuelTemp")),
            "agency": a.get("Agency"),
            "valid_utc": valid_utc,
        })
    return out


if __name__ == "__main__":
    import json
    import sys
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 47.34
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else -114.08
    stations = fetch_nearby(lat, lon, 75)
    print(f"{len(stations)} wind-instrumented RAWS stations within 75mi")
    for s in stations[:5]:
        print(" ", json.dumps(s))
