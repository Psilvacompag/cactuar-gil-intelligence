from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gil_intelligence.collectors import collect_aggregated_market
from gil_intelligence.probes.http import JsonHttpClient
from gil_intelligence.publishing import export_currency_dashboard
from gil_intelligence.storage import (
    import_static_snapshot,
    import_universalis_aggregates,
    prune_market_history,
)
from gil_intelligence.valuation import build_currency_valuations

from .config import CloudSettings
from .gcs import GcsObjectStore


def _emit(message: str, *, severity: str = "INFO", **fields: Any) -> None:
    print(
        json.dumps(
            {"severity": severity, "message": message, **fields},
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )


def run_refresh(settings: CloudSettings, store: GcsObjectStore, work_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    database_path = work_dir / "gil_intelligence.sqlite3"
    dashboard_path = work_dir / "dashboard.json"
    static_path = work_dir / "static_snapshot.json"
    for generated_path in (database_path, dashboard_path, static_path):
        generated_path.unlink(missing_ok=True)

    has_database = store.download_if_exists(settings.database_object, database_path)
    if not has_database:
        _emit("No cloud database found; bootstrapping from the static snapshot")
        if not store.download_if_exists(settings.static_snapshot_object, static_path):
            raise FileNotFoundError(
                f"Neither {settings.database_object} nor {settings.static_snapshot_object} exists"
            )
        static_summary = import_static_snapshot(static_path, database_path)
        _emit("Static catalog imported", **asdict(static_summary))

    started = time.monotonic()
    collected_at = datetime.now(timezone.utc).isoformat()
    client = JsonHttpClient(
        "https://universalis.app",
        timeout_seconds=settings.timeout_seconds,
        requests_per_second=settings.requests_per_second,
        max_retries=settings.retries,
        user_agent="cactuar-gil-intelligence/0.0.1 (+https://psilvacompag.github.io/cactuar-gil-intelligence/)",
    )
    marketable = client.get_json("/api/v2/marketable")
    if not isinstance(marketable.data, list) or not all(
        isinstance(item_id, int) and not isinstance(item_id, bool) and item_id > 0
        for item_id in marketable.data
    ):
        raise ValueError("Universalis marketable response was not a positive integer list")

    def report_progress(completed: int, total: int) -> None:
        if completed == 1 or completed == total or completed % 10 == 0:
            _emit("Market batch collected", completed=completed, total=total)

    collection = collect_aggregated_market(
        client,
        scope=settings.scope,
        item_ids=marketable.data,
        progress=report_progress,
    )
    elapsed_seconds = round(time.monotonic() - started, 1)
    market_summary = import_universalis_aggregates(
        collection.payload,
        database_path,
        scope=settings.scope,
        collected_at=collected_at,
        requested_items=len(collection.requested_item_ids),
        request_count=client.request_attempt_count,
        collection_elapsed_seconds=elapsed_seconds,
    )
    valuation_summary = build_currency_valuations(
        database_path,
        scope=settings.scope,
        price_basis="RECENT_AVG_SALE",
        fee_rate=settings.fee_rate,
        freshness_hours=settings.freshness_hours,
        market_snapshot_id=market_summary.snapshot_id,
    )
    dashboard_summary = export_currency_dashboard(
        database_path,
        dashboard_path,
        scope=settings.scope,
        valuation_run_id=valuation_summary.valuation_run_id,
    )
    retention_summary = prune_market_history(
        database_path,
        scope=settings.scope,
        keep_snapshots=settings.retention_runs,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    result = {
        "status": "success",
        "scope": settings.scope,
        "startedAt": collected_at,
        "completedAt": completed_at,
        "elapsedSeconds": elapsed_seconds,
        "requestCount": client.request_attempt_count,
        "successfulRequestCount": client.successful_request_count,
        "marketableItems": len(marketable.data),
        "batchCount": collection.batch_count,
        "marketSnapshotId": market_summary.snapshot_id,
        "valuationRunId": valuation_summary.valuation_run_id,
        "conversions": dashboard_summary.conversions,
        "currencies": dashboard_summary.currencies,
        "retainedMarketSnapshots": retention_summary.kept_snapshots,
        "removedMarketSnapshots": retention_summary.removed_snapshots,
        "databaseBytes": database_path.stat().st_size,
        "dashboardBytes": dashboard_path.stat().st_size,
    }

    store.upload_file(
        database_path,
        settings.database_object,
        content_type="application/vnd.sqlite3",
        cache_control="no-store",
    )
    store.upload_file(
        dashboard_path,
        settings.dashboard_object,
        content_type="application/json; charset=utf-8",
        cache_control="public, max-age=60",
    )
    status_content = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    store.upload_bytes(
        status_content,
        settings.status_object,
        content_type="application/json; charset=utf-8",
        cache_control="no-store",
    )
    run_object = f"runs/{completed_at[:10]}/{market_summary.snapshot_id}.json"
    store.upload_bytes(
        status_content,
        run_object,
        content_type="application/json; charset=utf-8",
        cache_control="no-store",
    )
    return result


def main() -> int:
    settings = CloudSettings.from_environ()
    store = GcsObjectStore(settings.bucket)
    work_dir = Path(os.environ.get("CACTUAR_WORK_DIR", "/tmp/cactuar"))
    try:
        result = run_refresh(settings, store, work_dir)
    except Exception as exc:
        _emit("Refresh failed", severity="ERROR", error=type(exc).__name__, detail=str(exc))
        raise
    _emit("Refresh completed", **result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
