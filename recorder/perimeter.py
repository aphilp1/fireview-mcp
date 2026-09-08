#!/usr/bin/env python3
"""
Fetches a fire's real mapped perimeter polygon from WFIGS_Daily_Perimeters_Public
-- the same feature service and query pattern FireView's fetch_perimeter.py used
for Silvertip, generalized to any incident name. This is a SEPARATE, slower-
updating product from WFIGS_Incident_Locations_Current (fire_resolution.py) --
per FireView's own documented experience, the daily perimeter polygon can lag
the incident-status acreage by hours to a day or more after a real growth event.
No fabrication: if the query returns nothing, or the matched feature has no ring
geometry, returns None rather than guessing a shape.
"""
import requests

SERVICE_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Daily_Perimeters_Public/FeatureServer/0/query"
)
OUT_FIELDS = ",".join([
    "poly_IncidentName", "poly_GISAcres", "poly_DateCurrent", "poly_PolygonDateTime",
    "poly_Source", "attr_FireBehaviorGeneral", "attr_PercentContained",
])


def fetch_perimeter(incident_name: str) -> dict | None:
    """Returns {'rings': [[[lon,lat],...], ...], 'acres', 'polygon_datetime_epoch_ms',
    'source', 'fire_behavior_general', 'percent_contained'} for the best (first,
    largest-acreage) match, or None if no mapped perimeter exists yet for this
    fire -- a real, expected outcome for a newly-detected or fast-moving fire,
    not an error.
    """
    params = {
        "where": f"poly_IncidentName = '{incident_name}'",
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    try:
        r = requests.get(SERVICE_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    features = data.get("features") or []
    if not features:
        return None

    # Multiple dated polygons can match (historical daily snapshots) -- take
    # the one with the most recent poly_DateCurrent, not just features[0].
    features.sort(key=lambda f: f.get("attributes", {}).get("poly_DateCurrent") or 0, reverse=True)
    feat = features[0]
    attrs = feat.get("attributes", {})
    rings = (feat.get("geometry") or {}).get("rings") or []
    if not rings or not rings[0]:
        return None

    return {
        "rings": rings,
        "acres": attrs.get("poly_GISAcres"),
        "polygon_datetime_epoch_ms": attrs.get("poly_PolygonDateTime"),
        "source": attrs.get("poly_Source"),
        "fire_behavior_general": attrs.get("attr_FireBehaviorGeneral"),
        "percent_contained": attrs.get("attr_PercentContained"),
    }


if __name__ == "__main__":
    import json
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "Silvertip"
    result = fetch_perimeter(name)
    if result is None:
        print(f"No mapped perimeter found for '{name}'.")
    else:
        n_rings = len(result["rings"])
        n_pts = sum(len(r) for r in result["rings"])
        print(f"{name}: {n_rings} ring(s), {n_pts} total points, "
              f"{result['acres']:.1f} ac, source={result['source']}")
