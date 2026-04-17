#!/usr/bin/env python3
"""Tiny local HTTP server used by the sample check plan and tests."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "ApiHealthFixture/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.write_json(200, {"status": "ok", "meta": {"version": "2026.04"}})
            return
        if self.path == "/api/orders":
            self.write_json(
                200,
                {
                    "data": [
                        {"id": "ord_1001", "status": "paid", "amount": 149.5},
                        {"id": "ord_1002", "status": "pending", "amount": 42.0}
                    ]
                },
            )
            return
        if self.path == "/private":
            self.write_json(401, {"error": "missing token"})
            return
        self.write_json(404, {"error": "not found"})

    def write_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local API health fixture server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FixtureHandler)
    print(f"fixture server listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
