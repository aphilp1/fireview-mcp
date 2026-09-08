#!/usr/bin/env python3
"""
Live TLE (two-line element) fetch for the 5 satellites FireView already
shows detections/imagery from -- MODIS (Terra, Aqua) and VIIRS (Suomi NPP,
NOAA-20, NOAA-21) -- so the dashboard can draw their real current orbital
ground tracks (the user's ask: "MODIS orbital paths, VIIRS path"), not just
imagery/detection points.

Agency facts, verified live 2026-09-06: Terra and Aqua (MODIS) are both NASA
satellites. Suomi NPP (Suomi National Polar-orbiting Partnership, launched
2011) is a genuinely joint NASA/NOAA satellite -- built under the original
NPOESS program and operated jointly -- and it carries VIIRS. NOAA-20 and
NOAA-21 (the JPSS-1/JPSS-2 follow-ons) also carry VIIRS but are
NOAA-operated, not joint NASA/NOAA in the same sense as Suomi NPP.

Source: CelesTrak's free, keyless `gp.php` endpoint -- verified live
2026-09-05, all 5 names return real current elements. CelesTrak does NOT set
CORS headers, so the browser can't fetch this directly (confirmed: no
Access-Control-Allow-Origin on the response) -- that's why this goes through
api_server.py's own /api/tle route instead of a client-side fetch.

TERRA's name search returns multiple fuzzy matches (e.g. "TERRASAR-X" is a
different, unrelated satellite) -- only the FIRST 3-line block is ever used,
since CelesTrak's own exact-name-first ordering is what the "NAME=" param
returns; parsed and logged once at build time to confirm before trusting.
Ground-track computation (propagation, geodetic conversion) happens
client-side via satellite.js, not here -- this module only fetches and
caches the raw elements.
"""
import time

import requests

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"
SATELLITES = ["TERRA", "AQUA", "SUOMI NPP", "NOAA 20", "NOAA 21"]
CACHE_TTL_S = 6 * 3600  # TLEs are re-issued roughly daily; no need to refetch every request

_cache = {"fetched_at": 0, "data": {}}


def _fetch_one(name: str):
    try:
        r = requests.get(CELESTRAK_URL, params={"NAME": name, "FORMAT": "TLE"}, timeout=20)
        r.raise_for_status()
        lines = [l for l in r.text.splitlines() if l.strip()]
        if len(lines) < 3:
            return None
        return {"name": lines[0].strip(), "line1": lines[1].strip(), "line2": lines[2].strip()}
    except Exception:
        return None


def fetch_all_tles(force: bool = False) -> dict:
    """{"TERRA": {"name":..., "line1":..., "line2":...}, ...} -- a satellite
    missing from the result means its live fetch failed (real, non-fatal;
    never fabricated)."""
    now = time.time()
    if not force and _cache["data"] and (now - _cache["fetched_at"]) < CACHE_TTL_S:
        return _cache["data"]
    out = {}
    for name in SATELLITES:
        tle = _fetch_one(name)
        if tle:
            out[name] = tle
    if out:
        _cache["data"] = out
        _cache["fetched_at"] = now
    return _cache["data"]


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_all_tles(force=True), indent=2))
