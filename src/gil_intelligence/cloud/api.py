from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .config import CloudSettings
from .dashboard import DashboardCache
from .gcs import GcsObjectStore


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_handler(
    cache: DashboardCache,
    history_cache: DashboardCache,
    market_items_cache: DashboardCache,
    market_history_cache: DashboardCache,
    opportunities_cache: DashboardCache,
    signals_cache: DashboardCache,
    settings: CloudSettings,
) -> type[BaseHTTPRequestHandler]:
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
                        "history": "/v1/history",
                        "marketItems": "/v1/market-items",
                        "marketHistory": "/v1/market-history",
                        "opportunities": "/v1/opportunities",
                        "signals": "/v1/signals",
                        "health": "/v1/health",
                    },
                )
                return
            if path == "/v1/health":
                self._serve_health()
                return
            if path in {"/v1/dashboard", "/dashboard.json"}:
                self._serve_document(cache)
                return
            if path == "/v1/history":
                self._serve_document(history_cache)
                return
            if path == "/v1/market-items":
                self._serve_document(market_items_cache)
                return
            if path == "/v1/market-history":
                self._serve_document(market_history_cache)
                return
            if path == "/v1/opportunities":
                self._serve_document(opportunities_cache)
                return
            if path == "/v1/signals":
                self._serve_document(signals_cache)
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
            age_hours = _age_hours(document.market_collected_at)
            is_stale = age_hours is None or age_hours > settings.max_data_age_hours
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE if is_stale else HTTPStatus.OK,
                {
                    "status": "stale" if is_stale else "ok",
                    "scope": settings.scope,
                    "dashboardGeneration": document.generation,
                    "dashboardUpdatedAt": document.updated_at,
                    "marketCollectedAt": document.market_collected_at,
                    "dataAgeHours": round(age_hours, 2) if age_hours is not None else None,
                    "maximumDataAgeHours": settings.max_data_age_hours,
                },
            )

        def _serve_document(self, document_cache: DashboardCache) -> None:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
                return
            try:
                document = document_cache.get()
            except Exception as exc:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "document_unavailable", "detail": type(exc).__name__},
                    origin=origin,
                )
                return
            use_gzip = _accepts_gzip(self.headers.get("Accept-Encoding"))
            content = document.compressed_content if use_gzip else document.content
            etag = document.etag[:-1] + '-gzip"' if use_gzip else document.etag
            if self.headers.get("If-None-Match") == etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self._send_security_headers(origin)
                self.send_header("Vary", "Accept-Encoding")
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(HTTPStatus.OK)
            self._send_security_headers(origin)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "public, max-age=300, stale-while-revalidate=900")
            self.send_header("Vary", "Accept-Encoding")
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(content)

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


def _accepts_gzip(value: str | None) -> bool:
    if not value:
        return False
    for entry in value.casefold().split(","):
        encoding, *parameters = (part.strip() for part in entry.split(";"))
        if encoding not in {"gzip", "*"}:
            continue
        quality = next((part for part in parameters if part.startswith("q=")), None)
        if quality is None:
            return True
        try:
            if float(quality[2:]) > 0:
                return True
        except ValueError:
            continue
    return False


def _age_hours(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return max(
        0.0,
        (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600,
    )


def main() -> int:
    settings = CloudSettings.from_environ()
    store = GcsObjectStore(settings.bucket)
    cache = DashboardCache(
        store,
        settings.dashboard_object,
        ttl_seconds=settings.cache_seconds,
    )
    history_cache = DashboardCache(
        store,
        settings.history_object,
        ttl_seconds=settings.cache_seconds,
        expected_kind="currency-history",
    )
    market_items_cache = DashboardCache(
        store,
        settings.market_items_object,
        ttl_seconds=settings.cache_seconds,
        expected_kind="market-items",
    )
    opportunities_cache = DashboardCache(
        store,
        settings.opportunities_object,
        ttl_seconds=settings.cache_seconds,
        expected_kind="market-opportunities",
    )
    signals_cache = DashboardCache(
        store,
        settings.signals_object,
        ttl_seconds=settings.cache_seconds,
        expected_kind="signal-ledger",
    )
    market_history_cache = DashboardCache(
        store,
        settings.market_history_object,
        ttl_seconds=settings.cache_seconds,
        expected_kind="market-history",
    )
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        build_handler(
            cache,
            history_cache,
            market_items_cache,
            market_history_cache,
            opportunities_cache,
            signals_cache,
            settings,
        ),
    )
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
