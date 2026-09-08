#!/usr/bin/env python3
"""
Classifies a fire's location into a region (CONUS / Alaska / Hawaii / other US
territory), which determines which data sources the recorder and forecaster can
assume are available. See ARCHITECTURE_SKETCH.md's region table -- availability
differs enough between these that downstream code must branch on this, not guess.
"""

# Two-letter POOState codes as returned by WFIGS (with "US-" prefix stripped).
ALASKA_CODES = {"AK"}
HAWAII_CODES = {"HI"}
# US territories WFIGS can report incidents in; data-source availability for
# these is untested and not designed for yet -- classified separately so the
# recorder can say so honestly rather than silently falling into a CONUS branch.
TERRITORY_CODES = {"PR", "VI", "GU", "AS", "MP"}


def classify_region(poo_state: str, lat: float, lon: float) -> str:
    """poo_state is WFIGS's POOState field, e.g. 'US-MT'. Returns one of
    'CONUS', 'Alaska', 'Hawaii', 'Territory', or 'Unknown'.
    """
    code = poo_state.replace("US-", "").strip().upper() if poo_state else ""

    if code in ALASKA_CODES:
        return "Alaska"
    if code in HAWAII_CODES:
        return "Hawaii"
    if code in TERRITORY_CODES:
        return "Territory"
    if code and len(code) == 2 and code.isalpha():
        return "CONUS"

    # Fallback purely on lat/lon if POOState is missing/malformed -- coarse
    # bounding boxes only, real enough to not misroute Alaska/Hawaii fires.
    if lat is not None and lon is not None:
        if lat > 50 and lon < -125:
            return "Alaska"
        if 18 <= lat <= 23 and -161 <= lon <= -154:
            return "Hawaii"
        if 24 <= lat <= 50 and -125 <= lon <= -66:
            return "CONUS"

    return "Unknown"


REGION_DATA_SOURCE_NOTES = {
    "CONUS": {
        "surface_stations": "IEM Mesonet ASOS/RWIS/RAWS(DCP), dense",
        "radiosondes": "NWS upper-air network, dense",
        "ridge_wind_proxy": "NRCS SNOTEL, common in the mountain west",
        "point_soundings": "College of DuPage GFS/NAM, confirmed working",
    },
    "Alaska": {
        "surface_stations": "IEM AK_ASOS exists; RAWS/DCP coverage untested, likely sparse",
        "radiosondes": "Sparse (Anchorage, Fairbanks, a handful more)",
        "ridge_wind_proxy": "SNOTEL exists in AK but density unknown",
        "point_soundings": "GFS is global so request should work; AK coverage of the specific tool untested",
    },
    "Hawaii": {
        "surface_stations": "IEM HI_ASOS exists; RAWS coverage unknown, terrain-driven microclimates weaken single-station representativeness",
        "radiosondes": "Only Hilo (PHTO) reliably",
        "ridge_wind_proxy": "No SNOTEL -- not snow country -- no ridge-wind proxy at all",
        "point_soundings": "Same global-GFS caveat as Alaska",
    },
    "Territory": {
        "surface_stations": "Untested, not designed for yet",
        "radiosondes": "Untested, not designed for yet",
        "ridge_wind_proxy": "Untested, not designed for yet",
        "point_soundings": "Untested, not designed for yet",
    },
    "Unknown": {
        "surface_stations": "Could not classify region -- verify POOState/coordinates before proceeding",
        "radiosondes": "Could not classify region -- verify POOState/coordinates before proceeding",
        "ridge_wind_proxy": "Could not classify region -- verify POOState/coordinates before proceeding",
        "point_soundings": "Could not classify region -- verify POOState/coordinates before proceeding",
    },
}


if __name__ == "__main__":
    tests = [
        ("US-MT", 47.82, -113.24),   # Silvertip -- CONUS
        ("US-AK", 64.8, -147.7),     # Fairbanks area -- Alaska
        ("US-HI", 19.6, -155.5),     # Big Island -- Hawaii
        ("US-PR", 18.2, -66.6),      # Puerto Rico -- Territory
        ("", None, None),            # malformed -- Unknown
    ]
    for poo, lat, lon in tests:
        region = classify_region(poo, lat, lon)
        print(f"{poo or '(none)':8s} ({lat},{lon}) -> {region}")
