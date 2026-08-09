from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


QUALITIES = ("NQ", "HQ")
SCOPE_LEVELS = ("DC", "REGION")


@dataclass(frozen=True, slots=True)
class MarketImportSummary:
    database_path: Path
    snapshot_id: str
    scope: str
    collected_at: str
    requested_items: int
    result_items: int
    failed_items: int
    aggregate_rows: int
    freshness_rows: int


def import_universalis_aggregates(
    payload: Any,
    database_path: Path | str,
    *,
    scope: str,
    collected_at: str,
    requested_items: int | None = None,
    source_url: str = "https://universalis.app/api/v2/aggregated",
    request_count: int | None = None,
    collection_elapsed_seconds: float | None = None,
) -> MarketImportSummary:
    """Normalize and atomically persist one collected Universalis snapshot."""
    normalized = _validate_payload(payload)
    normalized_collected_at = _normalize_iso_timestamp(collected_at)
    if not scope.strip():
        raise ValueError("scope must be a non-empty string")

    result_count = len(normalized["results"])
    failure_ids = _failure_ids(normalized["failedItems"])
    requested_count = requested_items if requested_items is not None else result_count + len(failure_ids)
    if isinstance(requested_count, bool) or not isinstance(requested_count, int) or requested_count < 0:
        raise ValueError("requested_items must be a non-negative integer")
    if requested_count < result_count + len(failure_ids):
        raise ValueError("requested_items cannot be smaller than results plus failures")
    if request_count is not None and (
        isinstance(request_count, bool) or not isinstance(request_count, int) or request_count <= 0
    ):
        raise ValueError("request_count must be a positive integer when provided")
    if collection_elapsed_seconds is not None and collection_elapsed_seconds < 0:
        raise ValueError("collection_elapsed_seconds must be non-negative when provided")

    canonical_payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    snapshot_key = f"universalis\0{scope}\0{normalized_collected_at}"
    snapshot_id = f"universalis:{hashlib.sha256(snapshot_key.encode('utf-8')).hexdigest()[:24]}"

    aggregate_rows: list[tuple[Any, ...]] = []
    freshness_rows: list[tuple[Any, ...]] = []
    seen_item_ids: set[int] = set()
    for result in normalized["results"]:
        item_id = _positive_int(result.get("itemId"), "result.itemId")
        if item_id in seen_item_ids:
            raise ValueError(f"Duplicate result itemId: {item_id}")
        seen_item_ids.add(item_id)
        aggregate_rows.extend(_aggregate_rows(snapshot_id, item_id, result))
        freshness_rows.extend(_freshness_rows(snapshot_id, item_id, result))

    target_path = Path(database_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        with connection:
            if _table_exists(connection, "currency_valuation_run"):
                connection.execute(
                    "DELETE FROM currency_valuation_run WHERE market_snapshot_id = ?",
                    (snapshot_id,),
                )
            connection.execute(
                "DELETE FROM market_source_snapshot WHERE market_snapshot_id = ?",
                (snapshot_id,),
            )
            connection.execute(
                """
                INSERT INTO market_source_snapshot (
                    market_snapshot_id, source, scope, collected_at, source_url,
                    requested_item_count, result_item_count, failed_item_count,
                    request_count, collection_elapsed_seconds, payload_sha256, imported_at
                ) VALUES (?, 'Universalis', ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    snapshot_id,
                    scope,
                    normalized_collected_at,
                    source_url,
                    requested_count,
                    result_count,
                    len(failure_ids),
                    request_count,
                    collection_elapsed_seconds,
                    payload_hash,
                ),
            )
            connection.executemany(
                """
                INSERT INTO fact_market_aggregate_snapshot (
                    market_snapshot_id, item_id, quality, scope_level,
                    min_listing_price, min_listing_world_id,
                    median_listing_price,
                    recent_purchase_price, recent_purchase_at, recent_purchase_world_id,
                    average_sale_price, daily_sale_velocity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                aggregate_rows,
            )
            connection.executemany(
                """
                INSERT INTO fact_data_freshness (
                    market_snapshot_id, item_id, world_id, uploaded_at
                ) VALUES (?, ?, ?, ?)
                """,
                freshness_rows,
            )
            connection.executemany(
                """
                INSERT INTO market_snapshot_failure (market_snapshot_id, item_id)
                VALUES (?, ?)
                """,
                ((snapshot_id, item_id) for item_id in failure_ids),
            )
    finally:
        connection.close()

    return MarketImportSummary(
        database_path=target_path.resolve(),
        snapshot_id=snapshot_id,
        scope=scope,
        collected_at=normalized_collected_at,
        requested_items=requested_count,
        result_items=result_count,
        failed_items=len(failure_ids),
        aggregate_rows=len(aggregate_rows),
        freshness_rows=len(freshness_rows),
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS market_source_snapshot (
            market_snapshot_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            scope TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            source_url TEXT NOT NULL,
            requested_item_count INTEGER NOT NULL CHECK (requested_item_count >= 0),
            result_item_count INTEGER NOT NULL CHECK (result_item_count >= 0),
            failed_item_count INTEGER NOT NULL CHECK (failed_item_count >= 0),
            request_count INTEGER,
            collection_elapsed_seconds REAL,
            payload_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fact_market_aggregate_snapshot (
            market_snapshot_id TEXT NOT NULL,
            item_id INTEGER NOT NULL CHECK (item_id > 0),
            quality TEXT NOT NULL CHECK (quality IN ('NQ', 'HQ')),
            scope_level TEXT NOT NULL CHECK (scope_level IN ('WORLD', 'DC', 'REGION')),
            min_listing_price REAL,
            min_listing_world_id INTEGER,
            median_listing_price REAL,
            recent_purchase_price REAL,
            recent_purchase_at TEXT,
            recent_purchase_world_id INTEGER,
            average_sale_price REAL,
            daily_sale_velocity REAL,
            PRIMARY KEY (market_snapshot_id, item_id, quality, scope_level),
            FOREIGN KEY (market_snapshot_id)
                REFERENCES market_source_snapshot(market_snapshot_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS fact_data_freshness (
            market_snapshot_id TEXT NOT NULL,
            item_id INTEGER NOT NULL CHECK (item_id > 0),
            world_id INTEGER NOT NULL CHECK (world_id > 0),
            uploaded_at TEXT NOT NULL,
            PRIMARY KEY (market_snapshot_id, item_id, world_id),
            FOREIGN KEY (market_snapshot_id)
                REFERENCES market_source_snapshot(market_snapshot_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS market_snapshot_failure (
            market_snapshot_id TEXT NOT NULL,
            item_id INTEGER NOT NULL CHECK (item_id > 0),
            PRIMARY KEY (market_snapshot_id, item_id),
            FOREIGN KEY (market_snapshot_id)
                REFERENCES market_source_snapshot(market_snapshot_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_market_aggregate_item
            ON fact_market_aggregate_snapshot(item_id, quality, scope_level, market_snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_data_freshness_item
            ON fact_data_freshness(item_id, uploaded_at);

        CREATE VIEW IF NOT EXISTS market_aggregate_with_freshness AS
        SELECT
            aggregate.*,
            snapshot.scope,
            snapshot.collected_at,
            MAX(freshness.uploaded_at) AS latest_upload_at
        FROM fact_market_aggregate_snapshot AS aggregate
        JOIN market_source_snapshot AS snapshot USING (market_snapshot_id)
        LEFT JOIN fact_data_freshness AS freshness
            ON freshness.market_snapshot_id = aggregate.market_snapshot_id
            AND freshness.item_id = aggregate.item_id
        GROUP BY
            aggregate.market_snapshot_id,
            aggregate.item_id,
            aggregate.quality,
            aggregate.scope_level;
        """
    )
    _ensure_column(connection, "fact_market_aggregate_snapshot", "median_listing_price", "REAL")
    _ensure_world_scope_level(connection)
    _ensure_column(connection, "market_source_snapshot", "request_count", "INTEGER")
    _ensure_column(
        connection,
        "market_source_snapshot",
        "collection_elapsed_seconds",
        "REAL",
    )


def _validate_payload(payload: Any) -> dict[str, list[Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Universalis payload root must be an object")
    results = payload.get("results")
    failed_items = payload.get("failedItems")
    if not isinstance(results, list) or not all(isinstance(row, dict) for row in results):
        raise ValueError("results must be a list of objects")
    if not isinstance(failed_items, list):
        raise ValueError("failedItems must be a list")
    return {"results": results, "failedItems": failed_items}


def _failure_ids(failed_items: list[Any]) -> list[int]:
    result: list[int] = []
    for value in failed_items:
        item_id = value.get("itemId") if isinstance(value, dict) else value
        result.append(_positive_int(item_id, "failedItems.itemId"))
    if len(result) != len(set(result)):
        raise ValueError("failedItems contains duplicate item IDs")
    return result


def _aggregate_rows(
    snapshot_id: str,
    item_id: int,
    result: dict[str, Any],
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for quality_key, quality in (("nq", "NQ"), ("hq", "HQ")):
        quality_data = _mapping(result.get(quality_key, {}), f"result.{quality_key}")
        metrics = {
            name: _mapping(quality_data.get(name, {}), f"result.{quality_key}.{name}")
            for name in (
                "minListing",
                "medianListing",
                "recentPurchase",
                "averageSalePrice",
                "dailySaleVelocity",
            )
        }
        api_levels = [("dc", "DC"), ("region", "REGION")]
        if any(metrics[name].get("world") for name in metrics):
            api_levels.insert(0, ("world", "WORLD"))
        for api_level, scope_level in api_levels:
            min_listing = _mapping(metrics["minListing"].get(api_level, {}), "minListing scope")
            median_listing = _mapping(metrics["medianListing"].get(api_level, {}), "medianListing scope")
            recent = _mapping(metrics["recentPurchase"].get(api_level, {}), "recentPurchase scope")
            average = _mapping(metrics["averageSalePrice"].get(api_level, {}), "averageSalePrice scope")
            velocity = _mapping(metrics["dailySaleVelocity"].get(api_level, {}), "dailySaleVelocity scope")
            rows.append(
                (
                    snapshot_id,
                    item_id,
                    quality,
                    scope_level,
                    _optional_number(min_listing.get("price"), "minListing.price"),
                    _optional_positive_int(min_listing.get("worldId"), "minListing.worldId"),
                    _optional_number(median_listing.get("price"), "medianListing.price"),
                    _optional_number(recent.get("price"), "recentPurchase.price"),
                    _optional_epoch_millis(recent.get("timestamp"), "recentPurchase.timestamp"),
                    _optional_positive_int(recent.get("worldId"), "recentPurchase.worldId"),
                    _optional_number(average.get("price"), "averageSalePrice.price"),
                    _optional_number(velocity.get("quantity"), "dailySaleVelocity.quantity"),
                )
            )
    return rows


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _ensure_world_scope_level(connection: sqlite3.Connection) -> None:
    table_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("fact_market_aggregate_snapshot",),
    ).fetchone()
    if table_sql_row is None or "'WORLD'" in table_sql_row[0]:
        return

    connection.executescript(
        """
        DROP VIEW IF EXISTS market_aggregate_with_freshness;
        ALTER TABLE fact_market_aggregate_snapshot
            RENAME TO fact_market_aggregate_snapshot_legacy;

        CREATE TABLE fact_market_aggregate_snapshot (
            market_snapshot_id TEXT NOT NULL,
            item_id INTEGER NOT NULL CHECK (item_id > 0),
            quality TEXT NOT NULL CHECK (quality IN ('NQ', 'HQ')),
            scope_level TEXT NOT NULL CHECK (scope_level IN ('WORLD', 'DC', 'REGION')),
            min_listing_price REAL,
            min_listing_world_id INTEGER,
            median_listing_price REAL,
            recent_purchase_price REAL,
            recent_purchase_at TEXT,
            recent_purchase_world_id INTEGER,
            average_sale_price REAL,
            daily_sale_velocity REAL,
            PRIMARY KEY (market_snapshot_id, item_id, quality, scope_level),
            FOREIGN KEY (market_snapshot_id)
                REFERENCES market_source_snapshot(market_snapshot_id) ON DELETE CASCADE
        );

        INSERT INTO fact_market_aggregate_snapshot (
            market_snapshot_id, item_id, quality, scope_level,
            min_listing_price, min_listing_world_id, median_listing_price,
            recent_purchase_price, recent_purchase_at, recent_purchase_world_id,
            average_sale_price, daily_sale_velocity
        )
        SELECT
            market_snapshot_id, item_id, quality, scope_level,
            min_listing_price, min_listing_world_id, median_listing_price,
            recent_purchase_price, recent_purchase_at, recent_purchase_world_id,
            average_sale_price, daily_sale_velocity
        FROM fact_market_aggregate_snapshot_legacy;

        DROP TABLE fact_market_aggregate_snapshot_legacy;

        CREATE INDEX idx_market_aggregate_item
            ON fact_market_aggregate_snapshot(item_id, quality, scope_level, market_snapshot_id);

        CREATE VIEW market_aggregate_with_freshness AS
        SELECT
            aggregate.*,
            snapshot.scope,
            snapshot.collected_at,
            MAX(freshness.uploaded_at) AS latest_upload_at
        FROM fact_market_aggregate_snapshot AS aggregate
        JOIN market_source_snapshot AS snapshot USING (market_snapshot_id)
        LEFT JOIN fact_data_freshness AS freshness
            ON freshness.market_snapshot_id = aggregate.market_snapshot_id
            AND freshness.item_id = aggregate.item_id
        GROUP BY
            aggregate.market_snapshot_id,
            aggregate.item_id,
            aggregate.quality,
            aggregate.scope_level;
        """
    )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _freshness_rows(
    snapshot_id: str,
    item_id: int,
    result: dict[str, Any],
) -> list[tuple[Any, ...]]:
    values = result.get("worldUploadTimes", [])
    if not isinstance(values, list) or not all(isinstance(row, dict) for row in values):
        raise ValueError("worldUploadTimes must be a list of objects")
    latest_by_world: dict[int, str] = {}
    for row in values:
        world_id = _positive_int(row.get("worldId"), "worldUploadTimes.worldId")
        uploaded_at = _optional_epoch_millis(row.get("timestamp"), "worldUploadTimes.timestamp")
        if uploaded_at is None:
            raise ValueError("worldUploadTimes.timestamp is required")
        latest_by_world[world_id] = max(uploaded_at, latest_by_world.get(world_id, uploaded_at))
    return [
        (snapshot_id, item_id, world_id, uploaded_at)
        for world_id, uploaded_at in sorted(latest_by_world.items())
    ]


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _optional_positive_int(value: Any, field: str) -> int | None:
    return None if value is None else _positive_int(value, field)


def _optional_number(value: Any, field: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field} must be a non-negative number")
    return value


def _optional_epoch_millis(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field} must be non-negative epoch milliseconds")
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _normalize_iso_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("collected_at must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("collected_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("collected_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()
