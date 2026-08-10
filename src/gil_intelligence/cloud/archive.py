from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path

from gil_intelligence.publishing import (
    export_currency_dashboard,
    export_currency_history,
    export_market_history,
    export_market_items,
    export_opportunities,
)
from gil_intelligence.storage import import_static_snapshot
from gil_intelligence.valuation import build_currency_valuations

from .bigquery_archive import BigQueryArchive
from .config import CloudSettings
from .gcs import GcsObjectStore


def main() -> int:
    settings = CloudSettings.from_environ()
    work_dir = Path(os.environ.get("CACTUAR_WORK_DIR", "/tmp/cactuar-archive"))
    work_dir.mkdir(parents=True, exist_ok=True)
    database_path = work_dir / "gil_intelligence.sqlite3"
    static_path = work_dir / "static_snapshot.json"
    dashboard_path = work_dir / "dashboard.json"
    history_path = work_dir / "history.json"
    market_items_path = work_dir / "market-items.json"
    market_history_path = work_dir / "market-history.json"
    opportunities_path = work_dir / "opportunities.json"
    for path in (
        database_path,
        static_path,
        dashboard_path,
        history_path,
        market_items_path,
        market_history_path,
        opportunities_path,
    ):
        path.unlink(missing_ok=True)
    store = GcsObjectStore(settings.bucket)
    if not store.download_if_exists(settings.database_object, database_path):
        raise FileNotFoundError(settings.database_object)
    valuation_summary = None
    if store.download_if_exists(settings.static_snapshot_object, static_path):
        snapshot_id = _static_snapshot_id(static_path)
        if not _has_static_snapshot(database_path, snapshot_id):
            import_static_snapshot(static_path, database_path)
            valuation_summary = build_currency_valuations(
                database_path,
                scope=settings.scope,
                price_basis="RECENT_AVG_SALE",
                fee_rate=settings.fee_rate,
                freshness_hours=settings.freshness_hours,
                static_snapshot_id=snapshot_id,
            )
    archive = BigQueryArchive(
        project_id=settings.project_id,
        dataset_id=settings.bigquery_dataset,
        location=settings.bigquery_location,
    )
    archive_summary = archive.archive_all(database_path, scope=settings.scope, work_dir=work_dir)
    dashboard_summary = export_currency_dashboard(database_path, dashboard_path, scope=settings.scope)
    history_summary = export_currency_history(database_path, history_path, scope=settings.scope)
    market_items_summary = export_market_items(
        database_path,
        market_items_path,
        scope=settings.scope,
        freshness_hours=settings.freshness_hours,
        fee_rate=settings.fee_rate,
    )
    market_history_summary = export_market_history(
        database_path,
        market_history_path,
        scope=settings.scope,
        max_snapshots=settings.retention_runs,
    )
    opportunities_summary = export_opportunities(
        database_path,
        opportunities_path,
        scope=settings.scope,
        fee_rate=settings.fee_rate,
    )
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
    print(
        json.dumps(
            {
                "archive": asdict(archive_summary),
                "staticRevaluation": (
                    asdict(valuation_summary) if valuation_summary is not None else None
                ),
                "dashboardConversions": dashboard_summary.conversions,
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
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
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


if __name__ == "__main__":
    raise SystemExit(main())
