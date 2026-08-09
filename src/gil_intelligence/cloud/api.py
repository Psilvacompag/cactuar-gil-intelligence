from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .config import CloudSettings
from .dashboard import DashboardCache
from .gcs import GcsObjectStore


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_handler(cache: DashboardCache, settings: CloudSettings) -> type[BaseHTTPRequestHandler]:
    allowed_origins = frozenset(settings.allowed_origins)

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "CactuarBackend/1.0"

        def do_OPTIONS(self) -> None:  # noqa: N802
            origin = self.headers.get("Origin")
            if origin not in allowed_origins:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_security_headers(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "If-None-Match")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "service": "cactuar-gil-intelligence",
                        "dashboard": "/v1/dashboard",
                        "health": "/v1/health",
                    },
                )
                return
            if path == "/v1/health":
                self._serve_health()
                return
            if path in {"/v1/dashboard", "/dashboard.json"}:
                self._serve_dashboard()
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def _serve_health(self) -> None:
            try:
                document = cache.get()
            except Exception as exc:  # Health must turn storage failures into a 503.
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "unavailable", "error": type(exc).__name__},
                )
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "scope": settings.scope,
                    "dashboardGeneration": document.generation,
                    "dashboardUpdatedAt": document.updated_at,
                },
            )

        def _serve_dashboard(self) -> None:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
                return
            try:
                document = cache.get()
            except Exception as exc:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "dashboard_unavailable", "detail": type(exc).__name__},
                    origin=origin,
                )
                return
            if self.headers.get("If-None-Match") == document.etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self._send_security_headers(origin)
                self.send_header("ETag", document.etag)
                self.end_headers()
                return
            self.send_response(HTTPStatus.OK)
            self._send_security_headers(origin)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(document.content)))
            self.send_header("Cache-Control", "public, max-age=60, stale-while-revalidate=300")
            self.send_header("ETag", document.etag)
            self.end_headers()
            self.wfile.write(document.content)

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any],
            *,
            origin: str | None = None,
        ) -> None:
            content = _json_bytes(payload)
            self.send_response(status)
            self._send_security_headers(origin)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)

        def _send_security_headers(self, origin: str | None) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            if origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def log_message(self, message: str, *args: object) -> None:
            print(
                _json_bytes(
                    {
                        "severity": "INFO",
                        "message": message % args,
                        "remote": self.client_address[0],
                    }
                ).decode("utf-8"),
                flush=True,
            )

    return DashboardHandler


def main() -> int:
    settings = CloudSettings.from_environ()
    store = GcsObjectStore(settings.bucket)
    cache = DashboardCache(
        store,
        settings.dashboard_object,
        ttl_seconds=settings.cache_seconds,
    )
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), build_handler(cache, settings))
    print(
        _json_bytes(
            {
                "severity": "INFO",
                "message": "Cactuar backend listening",
                "port": port,
                "bucket": settings.bucket,
                "object": settings.dashboard_object,
            }
        ).decode("utf-8"),
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
