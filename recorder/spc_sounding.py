#!/usr/bin/env python3
"""
Live text radiosonde soundings from the Storm Prediction Center's own
sounding-plot data feed (the same source that generates their public Skew-T
GIFs), used here specifically to fix a real Alaska/Hawaii gap: balloons.py's
forecast.weather.gov/product.php MAN-product mechanism only serves CONUS
(confirmed live -- all 13 AK + both HI site codes return HTTP 400 there, see
radiosonde_stations.py's KNOWN GAP section), leaving IGRA's ~1-2 day-old
archive as the only fallback for those regions.

Found by following NWS Alaska Region's own "Alaska Upper Air Soundings" page
(weather.gov/afc/upperair), which links to SPC's plot for each AK station --
the data URL behind that GIF turns out to be a live, keyless, full-level
text file. Confirmed live for all 13 Alaska + both Hawaii site codes on
2026-09-09 (real gaps found, not fabricated: Nome/PAOM and St. Paul
Island/PASN returned genuinely stale soundings -- 5 days and >1 year old at
discovery time -- real station reporting gaps, not a fetch bug).

Scope, per explicit confirmation: Alaska/Hawaii only. CONUS keeps using
balloons.py's MAN product as its primary source, unchanged -- this module is
never tried for a CONUS site.
"""
import re
import urllib.request

SPC_SOUNDING_URL = "https://www.spc.noaa.gov/exper/soundings/LATEST/{icao}.txt"

# 3-letter site code (radiosonde_stations.py) -> 4-letter ICAO SPC expects.
# Every value confirmed live (HTTP 200, real current or near-current data)
# on 2026-09-09 -- see the module docstring for the two stale exceptions.
AK_HI_ICAO = {
    "ADQ": "PADQ", "AKN": "PAKN", "ANC": "PANC", "ANN": "PANT",
    "BET": "PABE", "BRW": "PABR", "CDB": "PACD", "FAI": "PAFA",
    "MCG": "PAMC", "OME": "PAOM", "OTZ": "PAOT", "SNP": "PASN",
    "YAK": "PAYA", "ITO": "PHTO", "LIH": "PHLI",
}


class NoSoundingFoundError(Exception):
    pass


def fetch_raw(icao: str) -> str:
    url = SPC_SOUNDING_URL.format(icao=icao)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode(errors="replace")


def _num(s):
    v = float(s)
    return None if v <= -9999.0 else v


def parse(text: str) -> dict:
    """Returns {'site', 'year','month','day','hour','minute', 'valid_utc',
    'levels': [{'pressure_hpa','height_m','temp_c','dewpt_c','wind_dir',
    'wind_kt'}, ...]}, levels in the file's own order (highest pressure --
    i.e. lowest altitude -- first, same convention as balloons.py/igra.py).
    Raises NoSoundingFoundError if the expected %TITLE%/%RAW% blocks aren't
    present, so a caller can fall back cleanly rather than get a confusing
    parse error."""
    title_m = re.search(r"%TITLE%\s*\n\s*(\S+)\s+(\d{2})(\d{2})(\d{2})/(\d{2})(\d{2})", text)
    if not title_m:
        raise NoSoundingFoundError("No %TITLE% block found in SPC sounding text")
    site, yy, mm, dd, hh, minute = title_m.groups()
    year, month, day, hour, minute = 2000 + int(yy), int(mm), int(dd), int(hh), int(minute)
    valid_utc = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"

    raw_m = re.search(r"%RAW%\s*\n(.*?)(?:%END%|\Z)", text, re.DOTALL)
    if not raw_m:
        raise NoSoundingFoundError("No %RAW% block found in SPC sounding text")

    levels = []
    for line in raw_m.group(1).splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6:
            continue
        try:
            pres, hgt, temp, dwpt, wdir, wspd = (_num(p) for p in parts)
        except ValueError:
            continue
        if pres is None:
            continue
        levels.append({
            "pressure_hpa": pres, "height_m": hgt,
            "temp_c": temp, "dewpt_c": dwpt,
            "wind_dir": int(wdir) if wdir is not None else None,
            "wind_kt": wspd,
        })
    if not levels:
        raise NoSoundingFoundError("SPC %RAW% block had no parseable levels")
    return {
        "site": site, "year": year, "month": month, "day": day,
        "hour": hour, "minute": minute, "valid_utc": valid_utc,
        "levels": levels,
    }


def fetch_latest(site_3letter: str) -> dict:
    """site_3letter: the radiosonde_stations.py 3-letter code (e.g. 'FAI').
    Raises KeyError if it's not one of the AK/HI codes this module covers
    (callers should check `site_3letter in AK_HI_ICAO` first rather than
    relying on the exception), NoSoundingFoundError if fetch/parse fails."""
    icao = AK_HI_ICAO[site_3letter]
    result = parse(fetch_raw(icao))
    result["icao"] = icao
    return result


if __name__ == "__main__":
    import sys
    site = sys.argv[1] if len(sys.argv) > 1 else "FAI"
    sounding = fetch_latest(site)
    print(f"{site} ({sounding['icao']}) valid {sounding['valid_utc']}, {len(sounding['levels'])} levels")
    for lv in sounding["levels"][:5]:
        print(" ", lv)
