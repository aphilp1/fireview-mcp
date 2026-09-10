#!/usr/bin/env python3
"""
Real historical ground-sensor trends, combined into one area-averaged line
per network per variable, at four windows: 6h, 24h, 15d, 30d.

Scope, confirmed with the user before building:
- One combined (area-averaged) line per network, not per-station or one
  blended-across-networks line.
- Variables: wind, gust, temp, RH (SNOTEL has no RH element -- a real gap,
  left out for that network rather than guessed).
- RAWS excluded entirely -- no confirmed keyless historical source exists
  (NIFC's live feed is current-conditions-only; WRCC's own historical
  system needs a password beyond ~90 days and has no verified station-id
  crosswalk to NIFC's IDs; NOAA's own weather.gov/wrh/timeseries tool works
  but only via an Origin-header-spoofed use of a Synoptic key embedded for
  weather.gov's own use -- explicitly rejected as out of scope).
- IEM (ASOS/RWIS/DCP) has no batched historical endpoint (one station per
  request), so each of those three networks is capped at IEM_STATION_CAP
  representative stations for the combined average, to keep fetch time
  reasonable -- a real, labeled sample, not silently pretending it's every
  station.

Two real per-network data paths, not one uniform mechanism, because the
underlying APIs differ:
- SNOTEL and Montana Mesonet both have real single-call date-range hourly
  endpoints (confirmed live, no truncation across a real 30-day span), so
  one fetch per (batch of) stations covers all four windows -- sliced/
  resampled here, not re-fetched per window.
- IEM has no such endpoint: `obhistory.json` gives sub-hourly data for one
  LOCAL calendar day at a time (used for the 6h/24h windows, today +
  yesterday), and `daily.json` gives real daily min/max/avg aggregates for
  one calendar month at a time (used for the 15d/30d windows, current +
  previous month). IEM's daily aggregate has no avg temp/RH field, only
  min/max -- the midpoint of the day's real recorded min/max is used for
  those two variables at daily granularity, clearly a derived
  approximation, not a fabricated observation.
"""
import datetime
from concurrent.futures import ThreadPoolExecutor

import requests

IEM_OBHISTORY_URL = "https://mesonet.agron.iastate.edu/api/1/obhistory.json"
IEM_DAILY_URL = "https://mesonet.agron.iastate.edu/api/1/daily.json"
SNOTEL_DATA_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"
MTMESO_HOURLY_URL = "https://mesonet.climate.umt.edu/api/v2/observations/hourly/"

IEM_STATION_CAP = 15
WINDOWS = {"6h": 6, "24h": 24, "15d": 15 * 24, "30d": 30 * 24}  # all in hours


def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _bin_hourly(points):
    """points: [(epoch_seconds, value_or_None), ...]. Averages real values
    within each hour bucket; a bucket with nothing real is omitted."""
    buckets = {}
    for t, v in points:
        if v is None:
            continue
        b = int(t // 3600) * 3600
        buckets.setdefault(b, []).append(v)
    return {b: sum(vs) / len(vs) for b, vs in buckets.items()}


def _bin_daily(hourly_buckets):
    """hourly_buckets: {epoch_hour_start: value}. Re-averages into UTC
    calendar-day buckets."""
    buckets = {}
    for t, v in hourly_buckets.items():
        b = int(t // 86400) * 86400
        buckets.setdefault(b, []).append(v)
    return {b: sum(vs) / len(vs) for b, vs in buckets.items()}


# ---------------------------------------------------------------------------
# IEM (ASOS/RWIS/DCP) -- two-day obhistory for fine windows, two-month daily
# aggregates for the daily windows. One station at a time (no batching).
# ---------------------------------------------------------------------------

def _iem_fetch_obhistory(station, network, date):
    try:
        r = requests.get(IEM_OBHISTORY_URL, params={
            "station": station, "network": network, "date": date.strftime("%Y-%m-%d"),
        }, timeout=20)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def _iem_fetch_daily(station, network, year, month):
    try:
        r = requests.get(IEM_DAILY_URL, params={
            "station": station, "network": network, "year": year, "month": month,
        }, timeout=20)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def iem_station_fine_series(station, network):
    """Real sub-hourly obs for today + yesterday (UTC-approximate; covers
    any 6h/24h window regardless of time of day), hourly-binned. Returns
    {"wind_mph": {epoch_hour: v}, "gust_mph": {...}, "temp_f": {...}, "relh_pct": {...}}."""
    today = _now_utc()
    yesterday = today - datetime.timedelta(days=1)
    rows = _iem_fetch_obhistory(station, network, yesterday) + _iem_fetch_obhistory(station, network, today)

    series = {"wind_mph": [], "gust_mph": [], "temp_f": [], "relh_pct": []}
    for row in rows:
        valid = row.get("utc_valid")
        if not valid:
            continue
        t = datetime.datetime.strptime(valid, "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc).timestamp()
        sknt = row.get("sknt")
        series["wind_mph"].append((t, sknt * 1.15078 if sknt is not None else None))
        gust = row.get("gust")
        series["gust_mph"].append((t, gust * 1.15078 if gust is not None else None))
        series["temp_f"].append((t, row.get("tmpf")))
        series["relh_pct"].append((t, row.get("relh")))
    return {k: _bin_hourly(v) for k, v in series.items()}


def iem_station_daily_series(station, network):
    """Real daily aggregates for the current + previous calendar month,
    deduped by date, converted to {"wind_mph": {epoch_day: v}, ...}. Temp/RH
    at this granularity is the midpoint of IEM's real recorded daily
    min/max -- a derived approximation, not a fabricated observation."""
    today = _now_utc()
    prev_month = (today.replace(day=1) - datetime.timedelta(days=1))
    rows = {}
    for dt in (prev_month, today):
        for row in _iem_fetch_daily(station, network, dt.year, dt.month):
            d = row.get("date")
            if d:
                rows[d] = row  # de-dupe by real calendar date

    out = {"wind_mph": {}, "gust_mph": {}, "temp_f": {}, "relh_pct": {}}
    for d, row in rows.items():
        day_epoch = int(datetime.datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp())
        avg_sknt = row.get("avg_sknt")
        if avg_sknt is not None:
            out["wind_mph"][day_epoch] = avg_sknt * 1.15078
        max_gust = row.get("max_gust")
        if max_gust is not None:
            out["gust_mph"][day_epoch] = max_gust * 1.15078
        tmax, tmin = row.get("max_tmpf"), row.get("min_tmpf")
        if tmax is not None and tmin is not None:
            out["temp_f"][day_epoch] = (tmax + tmin) / 2
        rmax, rmin = row.get("max_rh"), row.get("min_rh")
        if rmax is not None and rmin is not None:
            out["relh_pct"][day_epoch] = (rmax + rmin) / 2
    return out


def fetch_iem_network_trends(stations, network):
    """stations: list of station id strings (already capped by the caller).
    Returns {"fine": {station: series}, "daily": {station: series}} for
    combining across stations by the caller."""
    with ThreadPoolExecutor(max_workers=max(1, len(stations) * 2)) as ex:
        fine_f = {s: ex.submit(iem_station_fine_series, s, network) for s in stations}
        daily_f = {s: ex.submit(iem_station_daily_series, s, network) for s in stations}
        fine = {s: f.result() for s, f in fine_f.items()}
        daily = {s: f.result() for s, f in daily_f.items()}
    return {"fine": fine, "daily": daily}


# ---------------------------------------------------------------------------
# SNOTEL -- one batched 30-day hourly call covers every window.
# ---------------------------------------------------------------------------

SNOTEL_ELEMENTS = ["WSPDV", "WSPDX", "TOBS"]  # no RH element on SNOTEL -- real gap


def fetch_snotel_trends(triplets):
    """triplets: list of stationTriplet strings. Returns {"fine": {triplet:
    series}, "daily": {triplet: series}} built from ONE real 30-day hourly
    fetch, sliced/resampled here rather than re-fetched per window."""
    if not triplets:
        return {"fine": {}, "daily": {}}
    end = _now_utc()
    begin = end - datetime.timedelta(days=30)
    params = {
        "stationTriplets": ",".join(triplets), "elements": ",".join(SNOTEL_ELEMENTS),
        "duration": "HOURLY", "beginDate": begin.strftime("%Y-%m-%d %H:%M"),
        "endDate": end.strftime("%Y-%m-%d %H:%M"), "periodRef": "END",
    }
    try:
        r = requests.get(SNOTEL_DATA_URL, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json() or []
    except Exception:
        payload = []

    fine, daily = {}, {}
    for entry in payload:
        triplet = entry.get("stationTriplet")
        hourly = {"wind_mph": {}, "gust_mph": {}, "temp_f": {}, "relh_pct": {}}
        for series in entry.get("data", []):
            code = series.get("stationElement", {}).get("elementCode")
            key = {"WSPDV": "wind_mph", "WSPDX": "gust_mph", "TOBS": "temp_f"}.get(code)
            if not key:
                continue
            pts = []
            for v in series.get("values", []):
                try:
                    t = datetime.datetime.strptime(v["date"], "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc).timestamp()
                except (ValueError, KeyError):
                    continue
                pts.append((t, v.get("value")))
            hourly[key] = _bin_hourly(pts)
        fine[triplet] = hourly
        daily[triplet] = {k: _bin_daily(v) for k, v in hourly.items()}
    return {"fine": fine, "daily": daily}


# ---------------------------------------------------------------------------
# Montana Mesonet -- one batched 30-day hourly call covers every window.
# ---------------------------------------------------------------------------

MTMESO_ELEMENTS = ["wind_spd", "windgust", "air_temp", "rh"]
MTMESO_KEY_MAP = {
    "Wind Speed @ 10 m [mi/h]": "wind_mph", "Wind Speed @ 8 ft [mi/h]": "wind_mph",
    "Gust Speed @ 10 m [mi/h]": "gust_mph", "Gust Speed @ 8 ft [mi/h]": "gust_mph",
    "Air Temperature @ 2 m [°F]": "temp_f", "Air Temperature @ 8 ft [°F]": "temp_f",
    "Relative Humidity [%]": "relh_pct",
}


def fetch_mt_mesonet_trends(station_codes):
    """station_codes: list of Montana Mesonet station code strings. Returns
    {"fine": {code: series}, "daily": {code: series}} from ONE real 30-day
    batched hourly fetch (confirmed live: no truncation across a real
    30-day span, 654/720 real hours for a working test station)."""
    if not station_codes:
        return {"fine": {}, "daily": {}}
    end = _now_utc()
    begin = end - datetime.timedelta(days=30)
    params = {
        "stations": ",".join(station_codes), "elements": ",".join(MTMESO_ELEMENTS),
        "start_time": begin.strftime("%Y-%m-%d"), "end_time": end.strftime("%Y-%m-%d"), "type": "json",
    }
    try:
        r = requests.get(MTMESO_HOURLY_URL, params=params, timeout=30)
        r.raise_for_status()
        rows = r.json() or []
    except Exception:
        rows = []

    per_station = {}
    for row in rows:
        code = row.get("station")
        t = row.get("datetime")
        if code is None or t is None:
            continue
        t_s = t / 1000.0
        bucket = per_station.setdefault(code, {"wind_mph": [], "gust_mph": [], "temp_f": [], "relh_pct": []})
        for raw_key, mapped in MTMESO_KEY_MAP.items():
            if raw_key in row and row[raw_key] is not None:
                bucket[mapped].append((t_s, row[raw_key]))

    fine, daily = {}, {}
    for code, series in per_station.items():
        hourly = {k: _bin_hourly(v) for k, v in series.items()}
        fine[code] = hourly
        daily[code] = {k: _bin_daily(v) for k, v in hourly.items()}
    return {"fine": fine, "daily": daily}


# ---------------------------------------------------------------------------
# Combine: average across a network's stations at each aligned bin.
# ---------------------------------------------------------------------------

def _combine_stations(station_series_map, hours_back, bin_seconds):
    """station_series_map: {station: {var: {epoch_bucket: value}}}. Real
    area-average across stations at each bucket present in the cutoff
    window -- a bucket only one station has is still shown (real partial
    coverage), never interpolated across time."""
    cutoff = _now_utc().timestamp() - hours_back * 3600
    out = {}
    variables = ["wind_mph", "gust_mph", "temp_f", "relh_pct"]
    for var in variables:
        by_bucket = {}
        for series in station_series_map.values():
            for b, v in series.get(var, {}).items():
                if b < cutoff:
                    continue
                by_bucket.setdefault(b, []).append(v)
        points = sorted((b, sum(vs) / len(vs), len(vs)) for b, vs in by_bucket.items())
        out[var] = [{"t": datetime.datetime.fromtimestamp(b, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "value": round(v, 1), "n": n} for b, v, n in points]
    return out


def build_network_trends(network_stations: dict) -> dict:
    """network_stations: {"MT_ASOS": [...station ids...], "SNTL": [...triplets...],
    "MTMESO": [...codes...], ...} -- already-resolved station lists for the
    query point (caller decides which real stations qualify; this module
    just fetches + combines). Returns {network: {window: {var: [...]}}} for
    every window in WINDOWS, network by network."""
    result = {}
    for network, stations in network_stations.items():
        if not stations:
            continue
        if network in ("SNTL", "SNTLT"):
            fetched = fetch_snotel_trends(stations)
        elif network == "MTMESO":
            fetched = fetch_mt_mesonet_trends(stations)
        else:  # IEM family: *_ASOS / *_RWIS / *_DCP
            fetched = fetch_iem_network_trends(stations[:IEM_STATION_CAP], network)

        result[network] = {}
        for window, hours in WINDOWS.items():
            source = fetched["fine"] if hours <= 24 else fetched["daily"]
            result[network][window] = _combine_stations(source, hours, 3600 if hours <= 24 else 86400)
    return result


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, ".")
    from stations import fetch_network_currents

    net = sys.argv[1] if len(sys.argv) > 1 else "MT_RWIS"
    obs = fetch_network_currents(net)
    ids = [o["station"] for o in obs[:5] if o.get("sknt") is not None]
    print(f"testing {net} with stations {ids}")
    trends = build_network_trends({net: ids})
    print(json.dumps(trends, indent=1)[:3000])
