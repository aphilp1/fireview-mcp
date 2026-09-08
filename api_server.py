#!/usr/bin/env python3
"""
Live local HTTP JSON API so the dashboard can let the user click anywhere on
the map and see the real sensor network around that point -- not just around
a resolved fire. This file contains NO sensor-fetching logic of its own; it
is a thin HTTP wrapper around build_sensor_snapshot.sensors_around_point(),
the same function every fire's static sensor_snapshot.json is built from.

Routes:
  GET /api/point?lat=<float>&lon=<float>&radius_km=<float, optional, default 121>
    -> {"point": {...}, "stations": [...], "snotel": [...], "soundings": [...]}
  GET /api/fire?name=<string>&radius_km=<float, optional, default 121>
    -> same shape as build_snapshot() -- {"fire": {...}, "perimeter": ..., "stations": [...], ...}
    Backs the single dashboard's fire-name search box, so ANY fire can be
    looked up live from one page instead of pre-baking a separate static
    dashboard per fire.

Usage: python api_server.py [port]   (default 8940)
"""
import http.server
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "recorder"))

from build_sensor_snapshot import sensors_around_point, build_snapshot
from fire_resolution import AmbiguousFireError, FireResolutionError
import orbital_tracks

DEFAULT_RADIUS_KM = 120.7008  # exactly 75 mi


class PointQueryHandler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_and_nocache_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_and_nocache_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_and_nocache_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    @staticmethod
    def _first_float(qs, key):
        vals = qs.get(key)
        if not vals:
            return None, False
        try:
            return float(vals[0]), True
        except ValueError:
            return None, False

    def _radius_km(self, qs):
        """Returns (radius_km, ok). ok=False means a response was already
        implied to be an error -- caller still must send it."""
        if "radius_km" not in qs:
            return DEFAULT_RADIUS_KM, True
        val, present = self._first_float(qs, "radius_km")
        return (val, True) if present else (None, False)

    def _handle_point(self, qs):
        lat_raw, lat_present = self._first_float(qs, "lat")
        lon_raw, lon_present = self._first_float(qs, "lon")
        if not lat_present or not lon_present:
            self._send_json(400, {"error": "missing or non-numeric required query params: lat, lon"})
            return
        radius_km, ok = self._radius_km(qs)
        if not ok:
            self._send_json(400, {"error": "radius_km must be numeric"})
            return
        try:
            result = sensors_around_point(lat_raw, lon_raw, radius_km)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, result)

    def _handle_fire(self, qs):
        names = qs.get("name")
        if not names or not names[0].strip():
            self._send_json(400, {"error": "missing required query param: name"})
            return
        radius_km, ok = self._radius_km(qs)
        if not ok:
            self._send_json(400, {"error": "radius_km must be numeric"})
            return
        try:
            result = build_snapshot(names[0].strip(), radius_km)
        except AmbiguousFireError as e:
            self._send_json(409, {"error": str(e), "ambiguous": True, "matches": e.matches})
            return
        except FireResolutionError as e:
            self._send_json(404, {"error": str(e)})
            return
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, result)

    def _handle_tle(self):
        # Server-side because CelesTrak sets no CORS header (confirmed --
        # a browser fetch straight to celestrak.org is blocked), and cached
        # in-process for hours since TLEs don't need per-query freshness --
        # see orbital_tracks.py.
        try:
            result = orbital_tracks.fetch_all_tles()
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, result)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/point":
            self._handle_point(qs)
        elif parsed.path == "/api/fire":
            self._handle_fire(qs)
        elif parsed.path == "/api/tle":
            self._handle_tle()
        else:
            self._send_json(404, {"error": f"unknown route: {parsed.path}"})

    def log_message(self, format, *args):
        # Default logging is fine, but keep it on stdout explicitly so
        # background-launched instances still show activity.
        sys.stdout.write("%s - %s\n" % (self.address_string(), format % args))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8940
    # Explicit IPv4 loopback bind -- see serve_dashboard.py's comment: the
    # IPv6-only default bind on some machine/Python combos silently refuses
    # plain 127.0.0.1 connections even while netstat shows it "Listening".
    # ThreadingHTTPServer (not the single-threaded default) since each
    # request makes several sequential live network calls (WFIGS, IEM, NRCS
    # AWDB, IGRA) -- a slow request must not block other requests.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), PointQueryHandler)
    print(f"Sensor API serving on http://127.0.0.1:{port}/api/point and /api/fire (no-cache, CORS *)")
    server.serve_forever()
