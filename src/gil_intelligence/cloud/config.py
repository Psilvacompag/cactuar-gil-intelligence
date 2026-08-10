from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_ALLOWED_ORIGINS = (
    "https://psilvacompag.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)


@dataclass(frozen=True, slots=True)
class CloudSettings:
    bucket: str
    project_id: str = "cactuar-gil-intelligence-8148"
    scope: str = "Cactuar"
    database_object: str = "state/gil_intelligence.sqlite3"
    static_snapshot_object: str = "catalog/static_snapshot.json"
    dashboard_object: str = "public/dashboard.json"
    history_object: str = "public/history.json"
    market_items_object: str = "public/market-items.json"
    opportunities_object: str = "public/opportunities.json"
    status_object: str = "status/latest.json"
    bigquery_dataset: str = "cactuar_gil"
    bigquery_location: str = "US"
    requests_per_second: float = 1.0
    timeout_seconds: float = 10.0
    retries: int = 2
    fee_rate: float = 0.05
    freshness_hours: float = 24.0
    retention_runs: int = 14
    cache_seconds: int = 60
    max_data_age_hours: float = 18.0
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "CloudSettings":
        source = os.environ if environ is None else environ
        bucket = source.get("CACTUAR_BUCKET", "").strip()
        if not bucket:
            raise ValueError("CACTUAR_BUCKET is required")

        origins_value = source.get("CACTUAR_ALLOWED_ORIGINS")
        allowed_origins = (
            tuple(origin.strip().rstrip("/") for origin in origins_value.split(",") if origin.strip())
            if origins_value is not None
            else DEFAULT_ALLOWED_ORIGINS
        )
        settings = cls(
            bucket=bucket.removeprefix("gs://").rstrip("/"),
            project_id=(
                source.get("CACTUAR_PROJECT_ID")
                or source.get("GOOGLE_CLOUD_PROJECT")
                or "cactuar-gil-intelligence-8148"
            ).strip(),
            scope=source.get("CACTUAR_SCOPE", "Cactuar").strip(),
            database_object=source.get(
                "CACTUAR_DATABASE_OBJECT", "state/gil_intelligence.sqlite3"
            ).strip(),
            static_snapshot_object=source.get(
                "CACTUAR_STATIC_OBJECT", "catalog/static_snapshot.json"
            ).strip(),
            dashboard_object=source.get(
                "CACTUAR_DASHBOARD_OBJECT", "public/dashboard.json"
            ).strip(),
            history_object=source.get(
                "CACTUAR_HISTORY_OBJECT", "public/history.json"
            ).strip(),
            market_items_object=source.get(
                "CACTUAR_MARKET_ITEMS_OBJECT", "public/market-items.json"
            ).strip(),
            opportunities_object=source.get(
                "CACTUAR_OPPORTUNITIES_OBJECT", "public/opportunities.json"
            ).strip(),
            status_object=source.get("CACTUAR_STATUS_OBJECT", "status/latest.json").strip(),
            bigquery_dataset=source.get("CACTUAR_BIGQUERY_DATASET", "cactuar_gil").strip(),
            bigquery_location=source.get("CACTUAR_BIGQUERY_LOCATION", "US").strip(),
            requests_per_second=float(source.get("CACTUAR_RPS", "1.0")),
            timeout_seconds=float(source.get("CACTUAR_HTTP_TIMEOUT", "10.0")),
            retries=int(source.get("CACTUAR_RETRIES", "2")),
            fee_rate=float(source.get("CACTUAR_FEE_RATE", "0.05")),
            freshness_hours=float(source.get("CACTUAR_FRESHNESS_HOURS", "24.0")),
            retention_runs=int(source.get("CACTUAR_RETENTION_RUNS", "14")),
            cache_seconds=int(source.get("CACTUAR_CACHE_SECONDS", "60")),
            max_data_age_hours=float(source.get("CACTUAR_MAX_DATA_AGE_HOURS", "18")),
            allowed_origins=allowed_origins,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.scope:
            raise ValueError("CACTUAR_SCOPE must not be empty")
        if not self.project_id:
            raise ValueError("CACTUAR_PROJECT_ID must not be empty")
        for field_name in (
            "database_object",
            "static_snapshot_object",
            "dashboard_object",
            "history_object",
            "market_items_object",
            "opportunities_object",
            "status_object",
            "bigquery_dataset",
            "bigquery_location",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if self.requests_per_second <= 0:
            raise ValueError("CACTUAR_RPS must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("CACTUAR_HTTP_TIMEOUT must be positive")
        if self.retries < 0:
            raise ValueError("CACTUAR_RETRIES must be non-negative")
        if not 0 <= self.fee_rate < 1:
            raise ValueError("CACTUAR_FEE_RATE must be between 0 and 1")
        if self.freshness_hours <= 0:
            raise ValueError("CACTUAR_FRESHNESS_HOURS must be positive")
        if self.retention_runs < 1:
            raise ValueError("CACTUAR_RETENTION_RUNS must be positive")
        if self.cache_seconds < 0:
            raise ValueError("CACTUAR_CACHE_SECONDS must be non-negative")
        if self.max_data_age_hours <= 0:
            raise ValueError("CACTUAR_MAX_DATA_AGE_HOURS must be positive")
