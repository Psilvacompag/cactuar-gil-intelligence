from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gil_intelligence.collectors import collect_aggregated_market, collect_detailed_listings
from gil_intelligence.probes.http import JsonHttpClient
from gil_intelligence.publishing import (
    export_currency_dashboard,
    export_currency_history,
    export_market_history,
    export_market_items,
    export_opportunities,
    export_signal_ledger,
)
from gil_intelligence.publishing.signal_candidates import signal_depth_candidates
from gil_intelligence.storage import (
    import_static_snapshot,
    import_detailed_listings,
    import_universalis_aggregates,
    prune_market_history,
)
from gil_intelligence.valuation import (
    DEFAULT_CURRENCY_PRICE_BASIS,
    build_currency_valuations,
)

from .bigquery_archive import BigQueryArchive
from .config import CloudSettings
from .gcs import GcsObjectStore
from .quality import evaluate_refresh_quality
from .users import FirebaseUserService


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
    history_path = work_dir / "history.json"
    market_items_path = work_dir / "market-items.json"
    market_history_path = work_dir / "market-history.json"
    opportunities_path = work_dir / "opportunities.json"
    signals_path = work_dir / "signals.json"
    static_path = work_dir / "static_snapshot.json"
    for generated_path in (
        database_path,
        dashboard_path,
        history_path,
        market_items_path,
        market_history_path,
        opportunities_path,
        signals_path,
        static_path,
    ):
        generated_path.unlink(missing_ok=True)

    has_database = store.download_if_exists(settings.database_object, database_path)
    has_static_snapshot = store.download_if_exists(settings.static_snapshot_object, static_path)
    if not has_database and not has_static_snapshot:
        raise FileNotFoundError(
            f"Neither {settings.database_object} nor {settings.static_snapshot_object} exists"
        )
    if not has_database:
        _emit("No cloud database found; bootstrapping from the static snapshot")
    if has_static_snapshot:
        static_snapshot_id = _static_snapshot_id(static_path)
        if not has_database or not _has_static_snapshot(database_path, static_snapshot_id):
            static_summary = import_static_snapshot(static_path, database_path)
            _emit("Static catalog imported", **asdict(static_summary))
    elif not has_database:
        raise FileNotFoundError(
            f"Neither {settings.database_object} nor {settings.static_snapshot_object} exists"
        )

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
        price_basis=DEFAULT_CURRENCY_PRICE_BASIS,
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
    quality_summary = evaluate_refresh_quality(database_path, dashboard_path, market_summary)
    export_opportunities(
        database_path,
        opportunities_path,
        scope=settings.scope,
        fee_rate=settings.fee_rate,
    )
    candidate_payload = json.loads(opportunities_path.read_text(encoding="utf-8"))
    candidates = list(candidate_payload.get("opportunities", []))
    export_market_items(
        database_path,
        market_items_path,
        scope=settings.scope,
        freshness_hours=settings.freshness_hours,
        fee_rate=settings.fee_rate,
    )
    export_market_history(
        database_path,
        market_history_path,
        scope=settings.scope,
        max_snapshots=settings.retention_runs,
    )
    signal_candidates = signal_depth_candidates(
        json.loads(market_items_path.read_text(encoding="utf-8")),
        json.loads(market_history_path.read_text(encoding="utf-8")),
    )
    reserved_home_pairs = {
        (candidate["sourceWorldId"], candidate["itemId"])
        for candidate in signal_candidates
    }
    dashboard_payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
    depth_candidates = _conversion_depth_candidates(
        dashboard_payload,
        limit=max(0, 100 - len(reserved_home_pairs)),
    )
    candidates.extend(signal_candidates)
    candidates.extend(depth_candidates)
    _emit(
        "Detailed listing shortlist prepared",
        opportunityCandidates=len(candidate_payload.get("opportunities", [])),
        signalDepthCandidates=len(signal_candidates),
        conversionDepthCandidates=len(depth_candidates),
    )
    detail_summary = None
    detail_error = None
    detail_batch_count = 0
    detail_requests_before = client.request_attempt_count

    def report_detail_progress(completed: int, total: int) -> None:
        _emit("Detailed listing batch collected", completed=completed, total=total)

    try:
        detailed_collection = collect_detailed_listings(
            client,
            candidates=candidates,
            listings_per_item=20,
            progress=report_detail_progress,
        )
        detail_batch_count = detailed_collection.batch_count
        detail_summary = import_detailed_listings(
            detailed_collection,
            database_path,
            market_snapshot_id=market_summary.snapshot_id,
            collected_at=datetime.now(timezone.utc).isoformat(),
            request_count=client.request_attempt_count - detail_requests_before,
        )
        _emit("Detailed listings imported", **asdict(detail_summary))
    except Exception as exc:
        detail_error = f"{type(exc).__name__}: {exc}"
        _emit(
            "Detailed listing validation failed; publishing unverified signals",
            severity="WARNING",
            detail=detail_error,
        )
    dashboard_summary = export_currency_dashboard(
        database_path,
        dashboard_path,
        scope=settings.scope,
        valuation_run_id=valuation_summary.valuation_run_id,
    )
    market_items_summary = export_market_items(
        database_path,
        market_items_path,
        scope=settings.scope,
        freshness_hours=settings.freshness_hours,
        fee_rate=settings.fee_rate,
    )
    opportunities_summary = export_opportunities(
        database_path,
        opportunities_path,
        scope=settings.scope,
        fee_rate=settings.fee_rate,
    )
    signal_summary = export_signal_ledger(
        database_path,
        signals_path,
        dashboard=json.loads(dashboard_path.read_text(encoding="utf-8")),
        market_items=json.loads(market_items_path.read_text(encoding="utf-8")),
        opportunities=json.loads(opportunities_path.read_text(encoding="utf-8")),
    )
    radar_summary = {"watched": 0, "recorded": 0}
    if settings.radar_history_enabled:
        try:
            radar_summary = FirebaseUserService(
                project_id=settings.project_id,
                bootstrap_admin_email=settings.bootstrap_admin_email,
                collection_name=settings.users_collection,
            ).record_favorite_observations(
                dashboard=json.loads(dashboard_path.read_text(encoding="utf-8")),
                market_items=json.loads(market_items_path.read_text(encoding="utf-8")),
                opportunities=json.loads(opportunities_path.read_text(encoding="utf-8")),
                signals=json.loads(signals_path.read_text(encoding="utf-8")),
            )
            _emit("Favorite radar observations recorded", **radar_summary)
        except Exception as exc:
            _emit(
                "Favorite radar history could not be recorded",
                severity="WARNING",
                error=type(exc).__name__,
                detail=str(exc),
            )
    archive = BigQueryArchive(
        project_id=settings.project_id,
        dataset_id=settings.bigquery_dataset,
        location=settings.bigquery_location,
    )
    archive_summary = archive.archive_all(
        database_path,
        scope=settings.scope,
        work_dir=work_dir,
    )
    retention_summary = prune_market_history(
        database_path,
        scope=settings.scope,
        keep_snapshots=settings.retention_runs,
    )
    history_summary = export_currency_history(
        database_path,
        history_path,
        scope=settings.scope,
    )
    market_history_summary = export_market_history(
        database_path,
        market_history_path,
        scope=settings.scope,
        max_snapshots=settings.retention_runs,
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
        "detailBatchCount": detail_batch_count,
        "detailItems": detail_summary.items if detail_summary else 0,
        "detailListings": detail_summary.listings if detail_summary else 0,
        "detailError": detail_error,
        "marketSnapshotId": market_summary.snapshot_id,
        "valuationRunId": valuation_summary.valuation_run_id,
        "conversions": dashboard_summary.conversions,
        "currencies": dashboard_summary.currencies,
        "historySeries": history_summary.series,
        "historyPoints": history_summary.points,
        "marketRows": market_items_summary.rows,
        "gatheringItems": market_items_summary.gathering_items,
        "craftingItems": market_items_summary.crafting_items,
        "profitableCrafts": market_items_summary.profitable_crafts,
        "marketHistorySeries": market_history_summary.series,
        "marketHistoryPoints": market_history_summary.points,
        "opportunities": opportunities_summary.opportunities,
        "highConfidenceOpportunities": opportunities_summary.high_confidence,
        "stockVerifiedOpportunities": opportunities_summary.stock_verified,
        "currentSignals": signal_summary.current_signals,
        "signalObservations": signal_summary.observations,
        "favoriteRadar": radar_summary,
        "quality": asdict(quality_summary),
        "bigQuery": asdict(archive_summary),
        "retainedMarketSnapshots": retention_summary.kept_snapshots,
        "removedMarketSnapshots": retention_summary.removed_snapshots,
        "databaseBytes": database_path.stat().st_size,
        "dashboardBytes": dashboard_path.stat().st_size,
        "historyBytes": history_path.stat().st_size,
        "marketItemsBytes": market_items_path.stat().st_size,
        "marketHistoryBytes": market_history_path.stat().st_size,
        "opportunitiesBytes": opportunities_path.stat().st_size,
        "signalsBytes": signals_path.stat().st_size,
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
        cache_control="public, max-age=300",
    )
    store.upload_file(
        history_path,
        settings.history_object,
        content_type="application/json; charset=utf-8",
        cache_control="public, max-age=300",
    )
    store.upload_file(
        market_items_path,
        settings.market_items_object,
        content_type="application/json; charset=utf-8",
        cache_control="public, max-age=300",
    )
    store.upload_file(
        market_history_path,
        settings.market_history_object,
        content_type="application/json; charset=utf-8",
        cache_control="public, max-age=300",
    )
    store.upload_file(
        opportunities_path,
        settings.opportunities_object,
        content_type="application/json; charset=utf-8",
        cache_control="public, max-age=300",
    )
    store.upload_file(
        signals_path,
        settings.signals_object,
        content_type="application/json; charset=utf-8",
        cache_control="public, max-age=300",
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
        failure = json.dumps(
            {
                "status": "failed",
                "failedAt": datetime.now(timezone.utc).isoformat(),
                "error": type(exc).__name__,
                "detail": str(exc),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            store.upload_bytes(
                failure,
                settings.status_object,
                content_type="application/json; charset=utf-8",
                cache_control="no-store",
            )
        except Exception as status_error:
            _emit(
                "Could not publish failure status",
                severity="ERROR",
                error=type(status_error).__name__,
            )
        raise
    _emit("Refresh completed", **result)
    return 0


def _static_snapshot_id(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return f"{payload['source']}:{payload['gameVersion']}:schema-{payload['schemaVersion']}"


def _has_static_snapshot(database_path: Path, snapshot_id: str) -> bool:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT 1 FROM source_snapshot WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    finally:
        connection.close()
    return row is not None


def _conversion_depth_candidates(
    dashboard: dict[str, Any],
    *,
    home_world_id: int = 79,
    limit: int = 100,
) -> list[dict[str, int]]:
    if limit < 1:
        return []
    conversions = dashboard.get("conversions")
    if not isinstance(conversions, list):
        return []
    eligible = [
        item
        for item in conversions
        if isinstance(item, dict)
        and item.get("status") == "FRESH"
        and isinstance(item.get("rewardItemId"), int)
        and not isinstance(item.get("rewardItemId"), bool)
        and item["rewardItemId"] > 0
        and isinstance(item.get("currencyItemId"), int)
        and isinstance(item.get("netGilPerCurrency"), (int, float))
        and item["netGilPerCurrency"] > 0
    ]
    eligible.sort(
        key=lambda item: (
            float(item["netGilPerCurrency"]),
            float(item.get("dailySaleVelocity") or 0),
        ),
        reverse=True,
    )
    selected: list[dict[str, int]] = []
    seen_rewards: set[int] = set()
    seen_currencies: set[int] = set()

    def add(item: dict[str, Any]) -> None:
        reward_id = int(item["rewardItemId"])
        if reward_id in seen_rewards or len(selected) >= limit:
            return
        seen_rewards.add(reward_id)
        seen_currencies.add(int(item["currencyItemId"]))
        selected.append({"itemId": reward_id, "sourceWorldId": home_world_id})

    for item in eligible:
        if item["currencyItemId"] not in seen_currencies:
            add(item)
        if len(selected) >= min(limit, 75):
            break
    liquid = sorted(
        eligible,
        key=lambda item: float(item["netGilPerCurrency"])
        * math.sqrt(max(0.0, float(item.get("dailySaleVelocity") or 0))),
        reverse=True,
    )
    for item in liquid:
        add(item)
        if len(selected) >= limit:
            break
    return selected


if __name__ == "__main__":
    raise SystemExit(main())
