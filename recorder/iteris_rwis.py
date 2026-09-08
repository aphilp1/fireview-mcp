#!/usr/bin/env python3
"""
State DOT RWIS+camera feeds on the Iteris ATIS platform's newer Mapbox-based
511 site architecture (found by inspecting 511mt.net's own JS state,
window.rwis_geo -> a public, keyless per-state GeoJSON CDN endpoint).

Iteris ATIS powers 511 for at least MT, SD, GA, KS, WV -- but confirmed by
direct inspection that they do NOT all share this same platform version:
Georgia's 511ga.org is a different (older, Google-Maps-based, ASP.NET
bundling) architecture with camera/RWIS data served through first-party
session-style endpoints (e.g. /map/Cctv/{id}), not this external CDN GeoJSON
pattern. KS and WV have not been checked and should NOT be assumed to match
either -- add a state here only after verifying its own feed the same way
MT and SD were (same URL pattern returns 200 AND the same feature schema).

ITERIS_STATES lists only states actually verified this way. Two real,
observed schema differences already found between MT and SD (don't assume
a third state matches either exactly without checking):
  - route: MT's `properties.route` holds just the route ("MT-16"); SD has no
    `route` key at all -- its `properties.description` holds the route
    instead ("US-16"). parse_station() below falls back route->description
    rather than guessing or fabricating one.
  - camera image URL pattern differs (MT: rwis_images/<code>.jpg; SD:
    camera_images/<station>/<n>/latest.jpg) -- irrelevant to us since we
    only ever use the URL the feed itself provides, never reconstruct one.
"""
import requests

ITERIS_STATES = {
    "MT": "https://mt.cdn.iteris-atis.com/geojson/icons/metadata/icons.rwis.geojson",
    "SD": "https://sd.cdn.iteris-atis.com/geojson/icons/metadata/icons.rwis.geojson",
}


def fetch_rwis(state_code: str) -> list:
    """Every RWIS station's raw GeoJSON feature for one verified state.
    Returns [] if the state isn't in ITERIS_STATES or the feed is
    unreachable -- both real, non-fatal outcomes."""
    url = ITERIS_STATES.get(state_code)
    if not url:
        return []
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json().get("features", [])
    except Exception:
        return []


def parse_station(feature: dict, state_code: str) -> dict:
    """Flattens one GeoJSON feature into the fields the dashboard needs.
    See module docstring for the real MT-vs-SD schema differences this
    already accounts for."""
    props = feature.get("properties", {})
    lon, lat = feature.get("geometry", {}).get("coordinates", [None, None])
    atmos_list = props.get("atmos") or []
    atmos = atmos_list[0] if atmos_list else {}
    surface_list = props.get("surface") or []
    surface = surface_list[0] if surface_list else {}

    def val(d, key):
        v = d.get(key)
        return v.get("value") if isinstance(v, dict) else None

    cameras = []
    for cam in props.get("cameras") or []:
        if cam.get("image"):
            cameras.append({
                "id": cam.get("id"), "name": cam.get("name"),
                "description": cam.get("description"),
                "image_url": cam.get("image"),
                "update_epoch_s": cam.get("updateTime"),
            })

    return {
        "id": feature.get("id"), "name": props.get("name"),
        "state": state_code,
        "route": props.get("route") or props.get("description"),
        "mrm": props.get("mrm"),
        "lat": lat, "lon": lon,
        "wind_mph": val(atmos, "wind_speed"), "gust_mph": val(atmos, "wind_gust"),
        "wind_dir_compass": val(atmos, "wind_direction"),
        "air_temp_f": val(atmos, "air_temperature"),
        "precip_type": val(atmos, "precip_type"),
        "surface_temp_f": val(surface, "surface_temperature"),
        "surface_condition": val(surface, "surface_condition"),
        "elevation_ft": val(surface, "elevation"),
        "observation_epoch_s": val(atmos, "observation_time"),
        "cameras": cameras,
    }


if __name__ == "__main__":
    import json
    import sys
    state = sys.argv[1] if len(sys.argv) > 1 else "MT"
    features = fetch_rwis(state)
    print(f"{state}: {len(features)} RWIS stations")
    if features:
        parsed = parse_station(features[0], state)
        print(json.dumps(parsed, indent=2))
        with_cams = sum(1 for f in features if (f.get("properties") or {}).get("cameras"))
        print(f"\n{with_cams}/{len(features)} stations have at least one camera")
