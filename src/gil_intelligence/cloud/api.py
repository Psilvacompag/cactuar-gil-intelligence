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
from .users import FirebaseUserService, UserApiError


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
    user_service: Any | None = None,
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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, If-None-Match")
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
                        "authConfig": "/v1/auth/config",
                        "me": "/v1/me",
                    },
                )
                return
            if path == "/v1/auth/config":
                origin = self._allowed_request_origin()
                if origin is False:
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "enabled": user_service is not None,
                        "provider": "google.com" if user_service is not None else None,
                        "firebase": settings.firebase_web_config if user_service is not None else None,
                    },
                    origin=origin,
                )
                return
            if path == "/v1/me":
                self._serve_private(lambda service: service.me(self.headers.get("Authorization")))
                return
            if path == "/v1/me/favorites":
                self._serve_private(
                    lambda service: {
                        "favorites": service.favorites(self.headers.get("Authorization"))
                    }
                )
                return
            if path == "/v1/admin/users":
                self._serve_private(
                    lambda service: {
                        "users": service.list_users(self.headers.get("Authorization")),
                        "invitations": service.list_invitations(
                            self.headers.get("Authorization")
                        ),
                    }
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

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/v1/auth/register":
                self._serve_private(
                    lambda service: service.register(self.headers.get("Authorization"))
                )
                return
            if path == "/v1/admin/invitations":
                self._serve_private(
                    lambda service: service.grant_access(
                        self.headers.get("Authorization"),
                        str(self._read_json().get("email") or ""),
                    )
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_PUT(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/v1/me/favorites":
                def save(service: Any) -> dict[str, Any]:
                    payload = self._read_json()
                    return service.put_favorite(
                        self.headers.get("Authorization"),
                        str(payload.get("key") or ""),
                        payload.get("metadata") or {},
                    )

                self._serve_private(save)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/v1/me/favorites":
                def remove(service: Any) -> dict[str, Any]:
                    payload = self._read_json()
                    service.delete_favorite(
                        self.headers.get("Authorization"),
                        str(payload.get("key") or ""),
                    )
                    return {"deleted": True}

                self._serve_private(remove)
                return
            if path == "/v1/admin/invitations":
                def revoke_invitation(service: Any) -> dict[str, Any]:
                    service.revoke_invitation(
                        self.headers.get("Authorization"),
                        str(self._read_json().get("id") or ""),
                    )
                    return {"deleted": True}

                self._serve_private(revoke_invitation)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_PATCH(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path.rstrip("/") or "/"
            prefix = "/v1/admin/users/"
            if path.startswith(prefix):
                uid = path[len(prefix):]
                self._serve_private(
                    lambda service: service.update_user(
                        self.headers.get("Authorization"), uid, self._read_json()
                    )
                )
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
            if not self._authorize_market_request(origin):
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
            self.send_header("Cache-Control", "private, max-age=300, stale-while-revalidate=900")
            self.send_header("Vary", "Accept-Encoding")
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(content)

        def _authorize_market_request(self, origin: str | None) -> bool:
            if user_service is None:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "authentication_not_configured"},
                    origin=origin,
                )
                return False
            try:
                user_service.authorize(self.headers.get("Authorization"))
            except UserApiError as exc:
                response = {"error": exc.code}
                if exc.detail:
                    response["detail"] = exc.detail
                self._send_json(exc.status, response, origin=origin)
                return False
            except Exception as exc:
                print(
                    _json_bytes(
                        {
                            "severity": "ERROR",
                            "message": "Market authorization failed",
                            "error": type(exc).__name__,
                        }
                    ).decode("utf-8"),
                    flush=True,
                )
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "internal_error"},
                    origin=origin,
                )
                return False
            return True

        def _allowed_request_origin(self) -> str | None | bool:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"})
                return False
            return origin

        def _serve_private(self, operation: Any) -> None:
            origin = self._allowed_request_origin()
            if origin is False:
                return
            if user_service is None:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "authentication_not_configured"},
                    origin=origin,
                )
                return
            try:
                self._read_payload = None
                payload = operation(user_service)
            except UserApiError as exc:
                response = {"error": exc.code}
                if exc.detail:
                    response["detail"] = exc.detail
                self._send_json(exc.status, response, origin=origin)
                return
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_request", "detail": str(exc)},
                    origin=origin,
                )
                return
            except Exception as exc:
                print(
                    _json_bytes(
                        {
                            "severity": "ERROR",
                            "message": "Private API operation failed",
                            "error": type(exc).__name__,
                        }
                    ).decode("utf-8"),
                    flush=True,
                )
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "internal_error"},
                    origin=origin,
                )
                return
            self._send_json(HTTPStatus.OK, payload, origin=origin)

        def _read_json(self) -> dict[str, Any]:
            cached = getattr(self, "_read_payload", None)
            if cached is not None:
                return cached
            value = self.headers.get("Content-Length") or "0"
            try:
                length = int(value)
            except ValueError as exc:
                raise ValueError("Content-Length inválido") from exc
            if length < 0 or length > 65536:
                raise ValueError("El cuerpo excede 64 KiB")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("JSON inválido") from exc
            if not isinstance(payload, dict):
                raise ValueError("El cuerpo debe ser un objeto JSON")
            self._read_payload = payload
            return payload

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
    firebase_config = settings.firebase_web_config
    user_service = (
        FirebaseUserService(
            project_id=settings.project_id,
            bootstrap_admin_email=settings.bootstrap_admin_email,
            collection_name=settings.users_collection,
        )
        if firebase_config is not None
        else None
    )
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
            user_service,
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
