#!/usr/bin/env python3
"""
Nearest wind-instrumented SNOTEL/SNOTEL-Lite stations, via the real NRCS AWDB
REST API -- the ridge/high-elevation wind proxy queued in ARCHITECTURE_SKETCH.md
("SNOTEL ridge-wind proxy (nearest station with a wind element, NRCS AWDB REST
API)"). Most SNOTEL stations only measure snow/precip/temp -- only a minority
carry an actual wind sensor (WDIRV/WSPDV/WSPDX), so this always filters to that
subset server-side rather than assuming every station qualifies.

Real regional limit, not a bug to work around: SNOTEL is a snow-monitoring
network. It has real coverage across the CONUS mountain west and Alaska, but
essentially none in Hawaii or the Pacific/Caribbean territories -- expect
fetch_wind_stations() to legitimately return [] there.
"""
import requests

BASE_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
WIND_ELEMENTS = ["WDIRV", "WSPDV", "WSPDX"]


def fetch_wind_stations(state: str) -> list:
    """Every active SNOTEL/SNOTEL-Lite station in `state` that carries at
    least one wind element. Returns [] on failure or if the state has no
    such stations -- both real, expected outcomes (e.g. HI, territories).
    """
    params = {
        "stationTriplets": f"*:{state}:SNTL,*:{state}:SNTLT",
        "activeOnly": "true",
        "returnStationElements": "true",
        "elements": ",".join(WIND_ELEMENTS),
    }
    try:
        r = requests.get(f"{BASE_URL}/stations", params=params, timeout=20)
        r.raise_for_status()
        return r.json() or []
    except Exception:
        return []


def fetch_latest_wind(station_triplet: str, lookback_hours: int = 24) -> dict:
    """Latest hourly WDIRV/WSPDV/WSPDX reading for one station. Real observed
    latency on these remote telemetry sites can run 6-10+ hours (verified live:
    Badger Pass, MT was 9.5 h behind at fetch time) -- a 6-hour window silently
    missed it, so the default is 24h. Returns {} if the window has no data for
    any element -- a real "not reporting" outcome, not fabricated.
    """
    import datetime
    end = datetime.datetime.now(datetime.timezone.utc)
    begin = end - datetime.timedelta(hours=lookback_hours)
    params = {
        "stationTriplets": station_triplet,
        "elements": ",".join(WIND_ELEMENTS),
        "duration": "HOURLY",
        "beginDate": begin.strftime("%Y-%m-%d %H:%M"),
        "endDate": end.strftime("%Y-%m-%d %H:%M"),
        "periodRef": "END",
    }
    try:
        r = requests.get(f"{BASE_URL}/data", params=params, timeout=20)
        r.raise_for_status()
        payload = r.json() or []
    except Exception:
        return {}

    if not payload:
        return {}
    out = {}
    for series in payload[0].get("data", []):
        code = series.get("stationElement", {}).get("elementCode")
        values = series.get("values", [])
        if code and values:
            latest = values[-1]
            out[code] = {"value": latest.get("value"), "date": latest.get("date")}
    return out


if __name__ == "__main__":
    import json
    import sys
    state = sys.argv[1] if len(sys.argv) > 1 else "MT"
    stations = fetch_wind_stations(state)
    print(f"{state}: {len(stations)} wind-instrumented SNOTEL/SNOTEL-Lite stations")
    if stations:
        s = stations[0]
        print("Sample:", s["name"], s["stationTriplet"], s["latitude"], s["longitude"])
        latest = fetch_latest_wind(s["stationTriplet"])
        print("Latest wind:", json.dumps(latest, indent=2))
