#!/usr/bin/env python3
"""
Fetches and decodes NWS TTAA radiosonde (weather balloon) soundings for any
upper-air site, and finds the nearest site(s) to a fire.

The FM-35 TTAA decode rules (temperature-sign parity, dewpoint-depression
threshold, wind-direction 100kt-carry digit) are protocol facts, not
Montana-specific ones, so this ports near-verbatim from FireView's
Documents\\FireView\\_cycle48_tmp\\decode.py -- validated there against real
Great Falls (TFX) and Spokane (OTX) soundings, see the self-test below, which
replays that same validated fixture. What's new here is that fetch/nearest_
sites are parameterized by site code instead of hardcoded to TFX/OTX, per
ARCHITECTURE_SKETCH.md's radiosonde section.
"""
import datetime
import json
import math
import re
import urllib.request

MAN_PRODUCT_URL = "https://forecast.weather.gov/product.php"
EARTH_RADIUS_KM = 6371.0


class NoSoundingFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Nearest-site lookup
# ---------------------------------------------------------------------------

def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_sites(lat: float, lon: float, stations: list, n: int = 2) -> list:
    """stations: list of dicts with at least 'site', 'lat', 'lon' (the format
    radiosonde_stations.py provides). Returns the n closest, each with a
    'distance_km' field added, nearest first. Stations missing lat/lon are
    skipped, not guessed.
    """
    candidates = []
    for st in stations:
        if st.get("lat") is None or st.get("lon") is None:
            continue
        d = _haversine_km(lat, lon, st["lat"], st["lon"])
        candidates.append({**st, "distance_km": d})
    candidates.sort(key=lambda s: s["distance_km"])
    return candidates[:n]


def sites_within(lat: float, lon: float, stations: list, max_km: float, cap: int = 6) -> list:
    """All real sites within max_km, nearest first, capped at `cap` (the
    real US radiosonde network is spaced roughly 200-500km apart, so a
    generous max_km can still return a handful in denser regions) -- this is
    what backs "give me ALL the available balloon information for this
    area" rather than an arbitrary fixed count regardless of what's
    actually nearby."""
    all_sorted = nearest_sites(lat, lon, stations, n=len(stations))
    return [s for s in all_sorted if s["distance_km"] <= max_km][:cap]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch(site: str, version: int) -> str:
    """Raw HTML for one issuance of a site's MAN (TTAA) product. version=1 is
    the most recent issuance, higher numbers step back in time. Returns the
    literal string starting with '__ERROR__' on failure rather than raising --
    callers loop over versions and need to keep going past a bad one.
    """
    url = f"{MAN_PRODUCT_URL}?site={site}&issuedby={site}&product=MAN&format=TXT&version={version}&glossary=0"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode(errors="replace")
    except Exception as e:
        return f"__ERROR__ {e}"


def parse_header_launch_time(header: str):
    """The MAN product header is a standard WMO abbreviated bulletin heading
    (e.g. "USUS45 KTFX 051203 COR"): the 6-digit group is DDHHMM (day-of-
    month, hour, minute UTC) -- a documented format, not guessed. No
    month/year is present in the heading itself, so it's inferred from the
    current UTC date (roll back a month if the heading's day is later than
    today's, meaning the bulletin is from the tail end of last month).
    Returns an ISO string, or None if the header doesn't match the format."""
    if not header:
        return None
    m = re.search(r"\b(\d{2})(\d{2})(\d{2})\b", header)
    if not m:
        return None
    day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month
    if day > now.day:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    try:
        dt = datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_pre(text: str):
    m = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.DOTALL)
    return m.group(1).strip() if m else None


def fetch_latest(site: str, max_versions: int = 8) -> dict:
    """Walks version=1..max_versions until it finds one with a decodable
    <pre> block and a header line. Returns {'site', 'header', 'pre', 'version'}.
    Raises NoSoundingFoundError if nothing decodable turns up -- this is a
    real "no data" outcome (site not reporting, network hiccup), not silently
    swallowed.
    """
    for v in range(1, max_versions + 1):
        text = fetch(site, v)
        pre = extract_pre(text)
        if not pre:
            continue
        header = None
        for line in pre.splitlines()[:5]:
            if re.search(r"\d{6}", line):
                header = line.strip()
                break
        return {"site": site, "header": header, "pre": pre, "version": v}
    raise NoSoundingFoundError(f"No decodable MAN product found for site {site} in versions 1-{max_versions}")


# ---------------------------------------------------------------------------
# FM-35 TTAA decode (ported from FireView's decode.py, unchanged logic)
# ---------------------------------------------------------------------------

def decode_temp_dewpt(g5: str):
    t3 = g5[:3]
    dd = g5[3:]
    t = int(t3) / 10.0
    parity_digit = int(t3[2])
    if parity_digit % 2 == 1:
        t = -t
    ddcode = int(dd)
    if ddcode <= 50:
        dep = ddcode / 10.0
    else:
        dep = ddcode - 50
    dewpt = t - dep
    return t, dewpt


def decode_wind(g5: str):
    ddd = int(g5[:3])
    ff = int(g5[3:])
    if ddd % 5 != 0:
        # Flag: direction not evenly divisible by 5 means the units digit
        # carries the "add 100kt to speed" flag instead of being part of the
        # true direction.
        flagged_digit = ddd % 10
        if flagged_digit == 1:
            true_ddd = ddd - 1
        elif flagged_digit == 6:
            true_ddd = ddd - 6
        else:
            true_ddd = ddd - (ddd % 5)
        ff += 100
        ddd = true_ddd
    return ddd, ff


LEVEL_ORDER = ["92", "85", "70", "50", "40", "30", "25", "20", "15", "10"]
# Thousands-digit height prefix, known reliably only for levels within the
# range FireView actually validated against real soundings (see decode.py's
# original comment -- 850/700 hPa heights in the observed event's range).
# Levels outside this dict get no height_m rather than a guessed one.
HEIGHTS_KNOWN = {"85": 1, "70": 3}


def parse_message(pre_text: str) -> dict:
    lines = [l for l in pre_text.splitlines() if l.strip()]
    groups = []
    for l in lines:
        groups.extend(l.split())

    ttaa_idx = groups.index("TTAA")
    idx = ttaa_idx + 3
    out = {}

    assert groups[idx].startswith("99"), groups[idx]
    surf_p = groups[idx]; idx += 1
    surf_td = groups[idx]; idx += 1
    surf_w = groups[idx]; idx += 1
    pcode = int(surf_p[2:])
    pres = pcode if pcode >= 500 else pcode + 1000
    t, dp = decode_temp_dewpt(surf_td)
    wd, ws = decode_wind(surf_w)
    out["surface"] = {
        "pressure_hpa": pres, "temp_c": t, "dewpt_c": dp,
        "wind_dir": wd, "wind_kt": ws, "raw": [surf_p, surf_td, surf_w],
    }

    idx += 3  # skip the "00PPP" 1000hPa/below-ground indicator group

    for lvl in LEVEL_ORDER:
        if idx + 2 >= len(groups):
            break
        hg = groups[idx]; tg = groups[idx + 1]; wg = groups[idx + 2]
        if not hg.startswith(lvl):
            found = None
            for j in range(idx, min(idx + 6, len(groups))):
                if groups[j].startswith(lvl):
                    found = j
                    break
            if found is None:
                continue
            idx = found
            hg = groups[idx]; tg = groups[idx + 1]; wg = groups[idx + 2]
        idx += 3
        rec = {"raw": [hg, tg, wg]}
        if tg != "/////" and wg != "/////":
            code3 = hg[2:]
            if code3 != "///":
                try:
                    codeval = int(code3)
                except ValueError:
                    codeval = None
                if lvl in HEIGHTS_KNOWN and codeval is not None:
                    rec["height_m"] = HEIGHTS_KNOWN[lvl] * 1000 + codeval
            if tg != "/////":
                t, dp = decode_temp_dewpt(tg)
                rec["temp_c"] = t
                rec["dewpt_c"] = dp
            if wg != "/////":
                wd, ws = decode_wind(wg)
                rec["wind_dir"] = wd
                rec["wind_kt"] = ws
        out[lvl] = rec
    return out


if __name__ == "__main__":
    # Replays FireView's own validated fixture (real fetched TFX soundings,
    # not synthetic) rather than hitting the live network on every run --
    # live fetch is exercised separately once a real site/fire is wired in.
    with open("_balloons_fixture.json") as f:
        fixture = json.load(f)

    print("=== VALIDATION: TFX v4 (cycle22's published 00Z Aug2 flight) ===")
    parsed = parse_message(fixture["TFX_v4"]["pre"])
    print("surface:", parsed["surface"])
    print("700:", parsed["70"])
    print("500:", parsed["50"])
    print("250:", parsed["25"])
    print()
    print("Expected from cycle22 log: surface T=38.0C dewpt=4.0C wind=070/18; "
          "700mb h=3156 T=16.2 dp=-1.8 wind=235/14; 500mb h=5589 T=-7.3 dp=-22.3 "
          "wind=235/46; 250mb h=10093 T=-43.1 dp=-48.1 wind=260/61")

    print()
    print("=== nearest_sites sanity check (Silvertip coords vs TFX/OTX) ===")
    silvertip = (47.82, -113.24)
    sample_stations = [
        {"site": "TFX", "name": "Great Falls, MT", "lat": 47.45, "lon": -111.38},
        {"site": "OTX", "name": "Spokane, WA", "lat": 47.68, "lon": -117.63},
        {"site": "RIW", "name": "Riverton, WY", "lat": 43.06, "lon": -108.48},
    ]
    for s in nearest_sites(*silvertip, sample_stations, n=3):
        print(f"  {s['site']:4s} {s['name']:20s} {s['distance_km']:.1f} km")
