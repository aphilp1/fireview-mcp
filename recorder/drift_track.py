#!/usr/bin/env python3
"""
Shared great-circle dead-reckoning math for radiosonde drift tracks, used by
BOTH data sources (previously only IGRA had a track at all). Same core idea
IGRA already used (igra.py's compute_drift_track): at each level, walk the
running position forward by wind_speed * dt in the direction the wind blows
TOWARD (wind_dir + 180, since WDIR is the meteorological "from" direction).

The two sources give genuinely different quality inputs, and that
difference is preserved on every track point via `height_basis`/`t_s_basis`
rather than papered over:
  - IGRA's y2d archive carries REAL elapsed time (etime_s) and REAL
    geopotential height (gph_m) per level -- the track's shape is only
    modeled (no per-level GPS fix), but its timing/height inputs are real.
  - The CONUS TTAA report carries neither: no elapsed time at all, and real
    height only at 850/700 hPa (see balloons.py's HEIGHTS_KNOWN). Missing
    heights fall back to the US Standard Atmosphere 1976 table below (a
    real published physical reference, not a same-day observation), and
    elapsed time is then derived from an assumed constant ascent rate
    (5 m/s / ~300 m/min, the standard operational figure). This stacks two
    assumptions, so CONUS-sourced tracks are labeled more conservatively.
"""
import math

EARTH_RADIUS_KM = 6371.0

# US Standard Atmosphere 1976 geopotential heights (meters) for each
# mandatory pressure level -- a real, published reference table, not a
# same-day observation. Used only when the report itself didn't decode a
# real height for that level.
STANDARD_ATM_HEIGHT_M = {
    925: 762, 850: 1457, 700: 3012, 500: 5574, 400: 7185,
    300: 9164, 250: 10363, 200: 11784, 150: 13608, 100: 16180,
}
DEFAULT_ASCENT_RATE_MPS = 5.0
MANDATORY_HPA = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100]


def dead_reckon(levels, launch_lat, launch_lon):
    """levels: sorted list of dicts, each at least {'t_s', 'wind_dir_deg',
    'wind_mps'}; any other keys are carried through onto the output point
    unchanged (so label/height/temp/pressure ride along with position).
    Returns [] if fewer than 2 usable levels."""
    if len(levels) < 2:
        return []
    track = [{**levels[0], "lat": launch_lat, "lon": launch_lon}]
    lat, lon = launch_lat, launch_lon
    for prev, cur in zip(levels, levels[1:]):
        dt = cur["t_s"] - prev["t_s"]
        if dt <= 0 or dt > 1800:  # skip bad/huge gaps rather than fabricate a jump
            continue
        toward_deg = (cur["wind_dir_deg"] + 180) % 360
        dist_km = (cur["wind_mps"] * dt) / 1000.0
        brg = math.radians(toward_deg)
        lat1, lon1 = math.radians(lat), math.radians(lon)
        d_r = dist_km / EARTH_RADIUS_KM
        lat2 = math.asin(math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brg))
        lon2 = lon1 + math.atan2(math.sin(brg) * math.sin(d_r) * math.cos(lat1), math.cos(d_r) - math.sin(lat1) * math.sin(lat2))
        lat, lon = math.degrees(lat2), math.degrees(lon2)
        track.append({**cur, "lat": lat, "lon": lon})
    return track


def conus_reckon_input(levels, ascent_rate_mps=DEFAULT_ASCENT_RATE_MPS):
    """levels: build_sensor_snapshot._conus_full_profile()'s output (one
    entry per real decoded mandatory level, already at most ~11 points --
    no further thinning needed)."""
    out = []
    for lv in levels:
        if lv.get("wind_kt") is None or lv.get("wind_dir") is None:
            continue
        if lv.get("label") == "Surface":
            t_s = 0.0
            height_basis = "launch"
            h = None
        else:
            h = lv.get("height_m")
            height_basis = "reported"
            if h is None:
                h = STANDARD_ATM_HEIGHT_M.get(lv.get("pressure_hpa"))
                height_basis = "standard_atmosphere_estimate"
            if h is None:
                continue
            t_s = h / ascent_rate_mps
        out.append({
            "t_s": t_s, "wind_dir_deg": lv["wind_dir"], "wind_mps": lv["wind_kt"] * 0.514444,
            "label": lv["label"], "pressure_hpa": lv.get("pressure_hpa"),
            "height_m": h, "height_basis": height_basis,
            "temp_c": lv.get("temp_c"), "dewpt_c": lv.get("dewpt_c"),
            "wind_dir": lv["wind_dir"], "wind_kt": lv["wind_kt"],
        })
    out.sort(key=lambda x: x["t_s"])
    return out


def igra_reckon_input(igra_levels):
    """igra_levels: raw sounding['levels'] from igra.fetch_latest_sounding()
    (real etime_s + gph_m + wind, no temp -- see that module's docstring).
    Filtered to levels near a mandatory pressure so the track stays a
    readable set of real turning points instead of every significant level
    in the archive (the full, unfiltered level list is still shown in the
    sidebar's table -- this filtering is drift-track-only)."""
    out = []
    for lv in igra_levels:
        if lv.get("etime_s") is None or lv.get("wind_mps") is None or lv.get("wind_dir") is None:
            continue
        if lv.get("pressure_pa") is None:
            continue
        hpa = round(lv["pressure_pa"] / 100)
        if not any(abs(hpa - m) <= 15 for m in MANDATORY_HPA):
            continue
        out.append({
            "t_s": lv["etime_s"], "wind_dir_deg": lv["wind_dir"], "wind_mps": lv["wind_mps"],
            "label": f"{hpa} hPa" if hpa != 1000 else "Surface", "pressure_hpa": hpa,
            "height_m": lv.get("gph_m"), "height_basis": "reported",
            "temp_c": None, "dewpt_c": None,
            "wind_dir": lv["wind_dir"], "wind_kt": round(lv["wind_mps"] * 1.94384, 1),
        })
    out.sort(key=lambda x: x["t_s"])
    return out
