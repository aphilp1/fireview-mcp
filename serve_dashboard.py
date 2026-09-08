#!/usr/bin/env python3
"""
Same as `python -m http.server <port>`, except every response is sent with
Cache-Control: no-store so the browser can never show a stale copy of a
dashboard/snapshot that gets rebuilt while a tab is already open on it. Plain
http.server doesn't set this -- same real gotcha already hit and fixed in
FireView's serve_dashboard.py for the Silvertip recording dashboard.

Usage: python serve_dashboard.py [port] [directory]
"""
import http.server
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8930
    directory = sys.argv[2] if len(sys.argv) > 2 else "."

    def handler(*args, **kwargs):
        NoCacheHandler(*args, directory=directory, **kwargs)

    # Explicit IPv4 loopback bind -- http.server.test()'s default bind (::)
    # is IPv6-only on some machine/Python combos, which silently refuses
    # plain 127.0.0.1 connections even while netstat shows it "Listening"
    # (verified real failure mode on FireView's serve_dashboard.py).
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Serving {directory} on http://127.0.0.1:{port}/ (no-cache)")
    server.serve_forever()
