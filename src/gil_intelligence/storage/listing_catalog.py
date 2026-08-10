from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gil_intelligence.collectors import DetailedListingCollection


@dataclass(frozen=True, slots=True)
class ListingImportSummary:
    database_path: Path
    detail_snapshot_id: str
    market_snapshot_id: str
    items: int
    listings: int
    request_count: int


def import_detailed_listings(
    collection: DetailedListingCollection,
    database_path: Path | str,
    *,
    market_snapshot_id: str,
    collected_at: str,
    request_count: int,
) -> ListingImportSummary:
    if request_count < 0:
        raise ValueError("request_count must be non-negative")
    normalized_collected_at = _iso_datetime(collected_at)
    canonical = json.dumps(collection.items, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
    detail_snapshot_id = f"universalis-detail:{hashlib.sha256(market_snapshot_id.encode()).hexdigest()[:24]}"
    target = Path(database_path)
    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        if connection.execute(
            "SELECT 1 FROM market_source_snapshot WHERE market_snapshot_id = ?",
            (market_snapshot_id,),
        ).fetchone() is None:
            raise ValueError(f"Unknown market snapshot: {market_snapshot_id}")
        status_rows: list[tuple[object, ...]] = []
        listing_rows: list[tuple[object, ...]] = []
        for item in collection.items:
            status_rows.append(
                (
                    detail_snapshot_id,
                    item["itemId"],
                    item["worldId"],
                    _epoch_datetime(item.get("lastUploadTime"), milliseconds=True),
                    len(item["listings"]),
                )
            )
            for listing in item["listings"]:
                listing_rows.append(
                    (
                        detail_snapshot_id,
                        item["itemId"],
                        item["worldId"],
                        "HQ" if listing["hq"] else "NQ",
                        listing["rank"],
                        listing.get("listingId"),
                        listing["pricePerUnit"],
                        listing["quantity"],
                        _epoch_datetime(listing.get("lastReviewTime"), milliseconds=False),
                    )
                )
        with connection:
            connection.execute(
                "DELETE FROM detail_source_snapshot WHERE market_snapshot_id = ?",
                (market_snapshot_id,),
            )
            connection.execute(
                """
                INSERT INTO detail_source_snapshot (
                    detail_snapshot_id, market_snapshot_id, collected_at,
                    requested_item_count, request_count, batch_count,
                    payload_sha256, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    detail_snapshot_id,
                    market_snapshot_id,
                    normalized_collected_at,
                    len(collection.requested_pairs),
                    request_count,
                    collection.batch_count,
                    payload_hash,
                ),
            )
            connection.executemany(
                """
                INSERT INTO detail_item_snapshot (
                    detail_snapshot_id, item_id, world_id,
                    last_upload_at, listings_returned
                ) VALUES (?, ?, ?, ?, ?)
                """,
                status_rows,
            )
            connection.executemany(
                """
                INSERT INTO fact_market_listing_snapshot (
                    detail_snapshot_id, item_id, world_id, quality,
                    listing_rank, listing_id, price_per_unit, quantity,
                    last_review_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                listing_rows,
            )
    finally:
        connection.close()
    return ListingImportSummary(
        database_path=target.resolve(),
        detail_snapshot_id=detail_snapshot_id,
        market_snapshot_id=market_snapshot_id,
        items=len(status_rows),
        listings=len(listing_rows),
        request_count=request_count,
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS detail_source_snapshot (
            detail_snapshot_id TEXT PRIMARY KEY,
            market_snapshot_id TEXT NOT NULL UNIQUE,
            collected_at TEXT NOT NULL,
            requested_item_count INTEGER NOT NULL CHECK (requested_item_count >= 0),
            request_count INTEGER NOT NULL CHECK (request_count >= 0),
            batch_count INTEGER NOT NULL CHECK (batch_count >= 0),
            payload_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            FOREIGN KEY (market_snapshot_id)
                REFERENCES market_source_snapshot(market_snapshot_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS detail_item_snapshot (
            detail_snapshot_id TEXT NOT NULL,
            item_id INTEGER NOT NULL CHECK (item_id > 0),
            world_id INTEGER NOT NULL CHECK (world_id > 0),
            last_upload_at TEXT,
            listings_returned INTEGER NOT NULL CHECK (listings_returned >= 0),
            PRIMARY KEY (detail_snapshot_id, item_id, world_id),
            FOREIGN KEY (detail_snapshot_id)
                REFERENCES detail_source_snapshot(detail_snapshot_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS fact_market_listing_snapshot (
            detail_snapshot_id TEXT NOT NULL,
            item_id INTEGER NOT NULL CHECK (item_id > 0),
            world_id INTEGER NOT NULL CHECK (world_id > 0),
            quality TEXT NOT NULL CHECK (quality IN ('NQ', 'HQ')),
            listing_rank INTEGER NOT NULL CHECK (listing_rank >= 0),
            listing_id TEXT,
            price_per_unit INTEGER NOT NULL CHECK (price_per_unit > 0),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            last_review_at TEXT,
            PRIMARY KEY (
                detail_snapshot_id, item_id, world_id, quality, listing_rank
            ),
            FOREIGN KEY (detail_snapshot_id)
                REFERENCES detail_source_snapshot(detail_snapshot_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_market_listing_item_world
            ON fact_market_listing_snapshot(item_id, world_id, quality, detail_snapshot_id);
        """
    )


def _iso_datetime(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("collected_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _epoch_datetime(value: object, *, milliseconds: bool) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    divisor = 1000 if milliseconds else 1
    return datetime.fromtimestamp(value / divisor, tz=timezone.utc).isoformat()
