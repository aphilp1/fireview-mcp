#!/usr/bin/env python3
"""
Resolves a fire name to its real WFIGS incident record. Queries
WFIGS_Incident_Locations_Current (the same live ArcGIS feature service FireView
used for Silvertip) filtered by IncidentName. If more than one active incident
matches, returns all matches rather than guessing -- the caller must disambiguate,
the same way a human would.
"""
import requests

WFIGS_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)


class FireResolutionError(Exception):
    pass


class AmbiguousFireError(FireResolutionError):
    def __init__(self, matches):
        self.matches = matches
        names = "; ".join(f"{m['IncidentName']} ({m['POOState']}, {m['IncidentSize']} ac)" for m in matches)
        super().__init__(f"{len(matches)} active incidents match: {names}")


def resolve_fire(name: str) -> dict:
    """Returns a dict with centroid lat/lon, state, acreage, containment,
    personnel, discovery date for the single matching active incident.
    Raises AmbiguousFireError if more than one matches, FireResolutionError if none do.
    """
    params = {
        "where": f"IncidentName LIKE '%{name}%'",
        "outFields": (
            "IncidentName,POOState,IncidentSize,PercentContained,"
            "TotalIncidentPersonnel,FireDiscoveryDateTime,IncidentTypeCategory,"
            "IncidentManagementOrganization,UniqueFireIdentifier"
        ),
        "f": "json",
        "returnGeometry": "true",
        "outSR": "4326",
    }
    r = requests.get(WFIGS_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    features = data.get("features", [])

    if not features:
        raise FireResolutionError(f"No active WFIGS incident matches name '{name}'")

    matches = []
    for f in features:
        attrs = f["attributes"]
        geom = f.get("geometry", {})
        matches.append({
            "IncidentName": attrs.get("IncidentName"),
            "POOState": attrs.get("POOState"),
            "IncidentSize": attrs.get("IncidentSize"),
            "PercentContained": attrs.get("PercentContained"),
            "TotalIncidentPersonnel": attrs.get("TotalIncidentPersonnel"),
            "FireDiscoveryDateTime": attrs.get("FireDiscoveryDateTime"),
            "IncidentTypeCategory": attrs.get("IncidentTypeCategory"),
            "UniqueFireIdentifier": attrs.get("UniqueFireIdentifier"),
            "lat": geom.get("y"),
            "lon": geom.get("x"),
        })

    if len(matches) > 1:
        raise AmbiguousFireError(matches)

    return matches[0]


if __name__ == "__main__":
    import sys, json
    name = sys.argv[1] if len(sys.argv) > 1 else "Silvertip"
    try:
        result = resolve_fire(name)
        print(json.dumps(result, indent=2))
    except AmbiguousFireError as e:
        print("AMBIGUOUS:", e)
        for m in e.matches:
            print(" -", json.dumps(m))
    except FireResolutionError as e:
        print("ERROR:", e)
