#!/usr/bin/env python3
"""
Resolves which states fall within radius_km of a fire's centroid (replacing
FireView's hardcoded MT/ID/WA list), builds the corresponding IEM Mesonet
network codes, and fetches current station observations.

State detection samples points around the fire at radius_km (N/S/E/W plus
intercardinals) and reverse-geocodes each via the Census Bureau's public
geocoder -- a real government API, no key required -- rather than embedding
state polygon boundaries. This is deliberately approximate (a circle isn't
covered by 8 samples) but matches the spirit of what FireView did by hand:
good enough to build a station network list, not a legal boundary determination.
"""
import math
from concurrent.futures import ThreadPoolExecutor

import requests

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
IEM_NETWORK_URL = "https://mesonet.agron.iastate.edu/geojson/network.php"
IEM_CURRENTS_URL = "https://mesonet.agron.iastate.edu/api/1/currents.json"

EARTH_RADIUS_KM = 6371.0


def _destination_point(lat, lon, bearing_deg, distance_km):
    lat1, lon1 = math.radians(lat), math.radians(lon)
    brg = math.radians(bearing_deg)
    d_r = distance_km / EARTH_RADIUS_KM
    lat2 = math.asin(math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def _reverse_geocode_state(lat, lon):
    params = {
        "x": lon, "y": lat, "benchmark": "Public_AR_Current",
        "vintage": "Current_Current", "layers": "states", "format": "json",
    }
    try:
        r = requests.get(CENSUS_GEOCODER_URL, params=params, timeout=15)
        r.raise_for_status()
        j = r.json()
        states = j.get("result", {}).get("geographies", {}).get("States", [])
        if states:
            return states[0].get("STUSAB")
    except Exception:
        pass
    return None


def nearby_states(lat: float, lon: float, radius_km: float) -> list:
    """Samples the fire's own location plus 8 points around a radius_km circle,
    reverse-geocodes each, returns the sorted unique list of state abbreviations
    touched. Best-effort: a failed sample point is skipped, not fatal.

    The 9 geocoder calls are independent HTTP round-trips (pure I/O wait) --
    run concurrently via a thread pool rather than sequentially, since this
    step alone was a real, measured chunk of the ~20-40s a point query used
    to take with everything done one call at a time.
    """
    points = [(lat, lon)] + [_destination_point(lat, lon, b, radius_km) for b in range(0, 360, 45)]
    with ThreadPoolExecutor(max_workers=len(points)) as ex:
        results = list(ex.map(lambda p: _reverse_geocode_state(*p), points))
    return sorted({st for st in results if st})


def build_network_codes(states: list) -> dict:
    """Returns {state: [network codes]} -- ASOS always requested; RWIS/DCP
    requested too since IEM simply returns empty for states without that
    program rather than erroring, so it's safe to always ask.
    """
    return {st: [f"{st}_ASOS", f"{st}_RWIS", f"{st}_DCP"] for st in states}


def fetch_network_stations(network_code: str) -> list:
    """Live station REGISTRY (metadata only -- lat/lon, elevation, WFO, etc,
    no observation values) for one IEM network. Returns [] if the network
    doesn't exist for this state (e.g. no RWIS program) -- that is a real,
    expected outcome, not an error to raise. For live wind/temp/etc values
    use fetch_network_currents() instead -- this endpoint doesn't carry them."""
    try:
        r = requests.get(IEM_NETWORK_URL, params={"network": network_code}, timeout=20)
        r.raise_for_status()
        j = r.json()
        return j.get("features", [])
    except Exception:
        return []


def fetch_network_currents(network_code: str) -> list:
    """Live CURRENT OBSERVATIONS (wind sknt/gust/drct, tmpf, relh, vsby, valid
    time, lat/lon) for every reporting station in one IEM network, via IEM's
    /api/1/currents.json endpoint. Distinct from fetch_network_stations()
    (registry metadata, no obs values) -- this is the one the sensor dashboard
    needs. Returns [] on any failure or empty network rather than raising."""
    try:
        r = requests.get(IEM_CURRENTS_URL, params={"network": network_code}, timeout=20)
        r.raise_for_status()
        j = r.json()
        return j.get("data", [])
    except Exception:
        return []


if __name__ == "__main__":
    import json
    # Silvertip's real coordinates, 75 mi (~121 km) radius -- the actual scope
    # FireView settled on and the user confirmed as intended (not the original 260km spec).
    lat, lon = 47.82, -113.24
    radius_km = 121
    states = nearby_states(lat, lon, radius_km)
    print("States within ~75mi of Silvertip's coordinates:", states)
    print("(FireView's real registry used MT, ID, WA -- checking recovery)")
    print()
    net_codes = build_network_codes(states)
    print(json.dumps(net_codes, indent=2))
    print()
    # Spot-check one real network fetch
    if states:
        test_net = f"{states[0]}_ASOS"
        stations = fetch_network_stations(test_net)
        print(f"Live fetch {test_net}: {len(stations)} stations returned")
        if stations:
            print("Sample:", json.dumps(stations[0], indent=2)[:500])
