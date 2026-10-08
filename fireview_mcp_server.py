"""
FireView MCP server -- one tool, `get_fire_sensor_report`.

Wraps `build_snapshot(fire_name, radius_km)` from build_sensor_snapshot.py as
a Model Context Protocol tool over stdio, so any MCP client (Claude Code,
Claude Desktop, or another agent) can ask for the live sensor network around a
named active US wildfire and get the same real data the dashboard shows.

In-process import, not an HTTP proxy: this does NOT need api_server.py to be
running. It hits the same upstream sources directly (NIFC WFIGS, IEM Mesonet,
NRCS AWDB, NWS/SPC/IGRA soundings, NASA FIRMS, Iteris RWIS, Montana Mesonet).

Run:
    py fireview_mcp_server.py            (stdio transport; the client spawns it)

Register with Claude Code (run once, from any directory):
    claude mcp add fireview -- py C:\\Users\\<you>\\Documents\\FireView-MCP\\fireview_mcp_server.py

Requires the `mcp` package, 2.x API (`pip install mcp`).
"""
import contextlib
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).parent))
from build_sensor_snapshot import build_snapshot, AmbiguousFireError, FireResolutionError  # noqa: E402

KM_PER_MI = 1.609344
DEFAULT_RADIUS_KM = 120.7008  # exactly 75 mi, same default as the dashboard and /api/fire

server = MCPServer(
    name="fireview",
    title="FireView live sensor feeds",
    instructions=(
        "Look up the live ground-sensor, sounding, radar, camera and satellite "
        "fire-detection network around a named active US wildfire. Fire names "
        "are matched against NIFC WFIGS active incidents with a substring "
        "search; if more than one incident matches, the result lists the "
        "candidates so the caller can retry with a more specific name."
    ),
)


def _station_row(s):
    return {
        "id": s.get("id"),
        "name": (s.get("name") or "").strip(),
        "network": s.get("network"),
        "dist_mi": s.get("dist_mi"),
        "elevation_ft": s.get("elevation_ft"),
        "wind_mph": s.get("wind_mph"),
        "gust_mph": s.get("gust_mph"),
        "dir_deg": s.get("dir_deg"),
        "temp_f": s.get("temp_f"),
        "relh_pct": s.get("relh_pct"),
        "fuel_moisture_pct": s.get("fuel_moisture_pct"),
        "valid_utc": s.get("valid_utc"),
    }


def _sounding_row(s):
    return {
        "site": s.get("site"),
        "name": s.get("name"),
        "dist_mi": s.get("dist_mi"),
        "status": s.get("status"),
        "source": s.get("source"),
        "launch_utc": s.get("launch_utc"),
        "surface_wind_mph": s.get("surface_wind_mph"),
        "surface_wind_dir": s.get("surface_wind_dir"),
        "level700_wind_mph": s.get("level700_wind_mph"),
        "level700_wind_dir": s.get("level700_wind_dir"),
        "levels": s.get("levels"),
    }


def _camera_row(c):
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "state": c.get("state"),
        "route": c.get("route"),
        "lat": c.get("lat"),
        "lon": c.get("lon"),
        "wind_mph": c.get("wind_mph"),
        "gust_mph": c.get("gust_mph"),
        "wind_dir_compass": c.get("wind_dir_compass"),
        "air_temp_f": c.get("air_temp_f"),
        "surface_condition": c.get("surface_condition"),
        "image_urls": [cam.get("image_url") for cam in (c.get("cameras") or []) if cam.get("image_url")],
    }


def _detection_summary(rows, key_conf):
    if not rows:
        return {"count": 0, "newest_hours_old": None, "max_frp_mw": None, "top_by_frp": []}
    by_frp = sorted(rows, key=lambda r: (r.get("frp_mw") or 0), reverse=True)
    return {
        "count": len(rows),
        "newest_hours_old": min((r.get("hours_old") for r in rows if r.get("hours_old") is not None), default=None),
        "max_frp_mw": by_frp[0].get("frp_mw"),
        "top_by_frp": [
            {
                "lat": r.get("lat"), "lon": r.get("lon"), "frp_mw": r.get("frp_mw"),
                "confidence": r.get(key_conf), "satellite": r.get("satellite"),
                "acq_utc": r.get("acq_utc"), "hours_old": r.get("hours_old"), "dist_mi": r.get("dist_mi"),
            }
            for r in by_frp[:10]
        ],
    }


def _report_from_snapshot(snap, elapsed_s):
    stations = snap.get("stations") or []
    snotel = snap.get("snotel") or []
    soundings = snap.get("soundings") or []
    cameras = snap.get("cameras") or []
    viirs = snap.get("viirs") or []
    modis = snap.get("modis") or []
    nexrad = snap.get("nexrad") or []
    perim = snap.get("perimeter")

    live_stations = [s for s in stations if s.get("wind_mph") is not None or s.get("temp_f") is not None]
    net_counts = Counter(s.get("network") for s in stations)

    return {
        "generated_utc": snap.get("generated_utc"),
        "fetch_seconds": round(elapsed_s, 1),
        "fire": snap.get("fire"),
        "perimeter": None if perim is None else {
            "acres": perim.get("acres"),
            "percent_contained": perim.get("percent_contained"),
            "fire_behavior_general": perim.get("fire_behavior_general"),
            "source": perim.get("source"),
            "ring_count": len(perim.get("rings") or []),
        },
        "data_status": {
            "ground_sensors_live": len(live_stations),
            "ground_sensors_total": len(stations),
            "ground_sensors_by_network": dict(sorted(net_counts.items())),
            "snotel": len(snotel),
            "soundings_ok": sum(1 for s in soundings if s.get("status") == "ok"),
            "soundings_total": len(soundings),
            "road_weather_camera_sites": len(cameras),
            "viirs_detections": len(viirs),
            "modis_detections": len(modis),
            "nexrad_sites": len(nexrad),
        },
        "ground_sensors": sorted((_station_row(s) for s in stations), key=lambda r: (r["dist_mi"] is None, r["dist_mi"])),
        "snotel": snotel,
        "soundings": [_sounding_row(s) for s in soundings],
        "road_weather_cameras": [_camera_row(c) for c in cameras],
        "fire_detections": {
            "viirs": _detection_summary(viirs, "confidence"),
            "modis": _detection_summary(modis, "confidence_pct"),
        },
        "nexrad": nexrad,
        "notes": [
            "Ground sensors are current conditions only (latest observation per station).",
            "Soundings: CONUS via NWS MAN product (near-immediate); Alaska/Hawaii via SPC (near-immediate); IGRA fallback runs 1-2 days behind and is labeled in 'source'.",
            "Fire detections are NASA FIRMS VIIRS/MODIS hotspots within the radius, not a perimeter.",
            "Perimeter rings are omitted here for size; the dashboard draws them.",
        ],
    }


@server.tool(
    name="get_fire_sensor_report",
    title="Live sensor report around an active US wildfire",
    description=(
        "Resolve an active US wildfire by name (NIFC WFIGS substring match) and "
        "return the live sensor network around it: ground weather stations "
        "(ASOS, RWIS, DCP, RAWS, Montana Mesonet), SNOTEL wind, radiosonde "
        "soundings, NEXRAD sites, road-weather cameras, and NASA FIRMS "
        "VIIRS/MODIS fire detections. Default radius is 75 miles (120.7 km). "
        "Typical fetch time is 5-20 seconds. If the name matches several "
        "incidents the result has 'ambiguous': true and a 'matches' list."
    ),
    structured_output=True,
)
def get_fire_sensor_report(fire_name: str, radius_km: float = DEFAULT_RADIUS_KM) -> dict[str, Any]:
    """fire_name: part or all of the incident name, e.g. "Aspen Acres".
    radius_km: search radius around the fire centroid in kilometers (default 120.7 km = 75 mi)."""
    name = (fire_name or "").strip()
    if not name:
        return {"error": "fire_name is required"}
    try:
        radius_km = float(radius_km)
    except (TypeError, ValueError):
        return {"error": "radius_km must be numeric"}
    if radius_km <= 0:
        return {"error": "radius_km must be positive"}

    t0 = time.monotonic()
    # stdio transport owns stdout; any stray print from the recorder goes to stderr instead.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            snap = build_snapshot(name, radius_km)
        except AmbiguousFireError as e:
            return {"error": str(e), "ambiguous": True, "matches": e.matches}
        except FireResolutionError as e:
            return {"error": str(e), "ambiguous": False, "matches": []}
    return _report_from_snapshot(snap, time.monotonic() - t0)


if __name__ == "__main__":
    server.run(transport="stdio")
