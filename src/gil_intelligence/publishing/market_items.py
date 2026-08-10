from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketItemsExportSummary:
    output_path: Path
    scope: str
    rows: int
    gathering_items: int
    crafting_items: int


def export_market_items(
    database_path: Path | str,
    output_path: Path | str,
    *,
    scope: str,
    freshness_hours: float = 24.0,
    home_world_id: int = 79,
) -> MarketItemsExportSummary:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        market = connection.execute(
            """
            SELECT market_snapshot_id, collected_at
            FROM market_source_snapshot
            WHERE lower(scope) = lower(?)
            ORDER BY collected_at DESC, market_snapshot_id DESC
            LIMIT 1
            """,
            (scope,),
        ).fetchone()
        if market is None:
            raise ValueError(f"No market snapshot is available for scope {scope!r}")
        static = connection.execute(
            """
            SELECT snapshot_id, game_version
            FROM source_snapshot
            ORDER BY extracted_at DESC, schema_version DESC, imported_at DESC
            LIMIT 1
            """
        ).fetchone()
        if static is None:
            raise ValueError("No static snapshot is available")
        rows = connection.execute(
            """
            WITH freshness AS (
                SELECT item_id, MAX(uploaded_at) AS latest_upload_at
                FROM fact_data_freshness
                WHERE market_snapshot_id = ?
                  AND world_id = ?
                GROUP BY item_id
            )
            SELECT asset.item_id, asset.name, asset.search_category_id,
                   asset.search_category_name, asset.ui_category_id,
                   asset.ui_category_name, asset.craftable,
                   asset.craft_type_name, asset.gatherable,
                   asset.gathering_type, market.quality,
                   market.min_listing_price, market.median_listing_price,
                   market.average_sale_price, market.daily_sale_velocity,
                   freshness.latest_upload_at
            FROM dim_asset AS asset
            JOIN fact_market_aggregate_snapshot AS market
              ON market.market_snapshot_id = ?
             AND market.item_id = asset.item_id
             AND market.scope_level = 'WORLD'
            LEFT JOIN freshness ON freshness.item_id = asset.item_id
            WHERE asset.snapshot_id = ?
              AND asset.marketable_candidate = 1
              AND (asset.craftable = 1 OR asset.gatherable = 1)
              AND market.daily_sale_velocity IS NOT NULL
              AND market.daily_sale_velocity > 0
            ORDER BY market.daily_sale_velocity DESC, asset.item_id, market.quality
            """,
            (
                market["market_snapshot_id"],
                home_world_id,
                market["market_snapshot_id"],
                static["snapshot_id"],
            ),
        ).fetchall()
    finally:
        connection.close()

    generated_at = datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    gathering_ids: set[int] = set()
    crafting_ids: set[int] = set()
    fresh_rows = 0
    for row in rows:
        latest_upload_at = _utc_datetime(row["latest_upload_at"])
        age_hours = (
            (generated_at - latest_upload_at).total_seconds() / 3600
            if latest_upload_at is not None
            else None
        )
        status = "FRESH" if age_hours is not None and age_hours <= freshness_hours else "STALE"
        fresh_rows += int(status == "FRESH")
        velocity = row["daily_sale_velocity"]
        average_price = row["average_sale_price"]
        daily_revenue = (
            float(velocity) * float(average_price)
            if velocity is not None and average_price is not None
            else None
        )
        craftable = bool(row["craftable"])
        gatherable = bool(row["gatherable"])
        if craftable:
            crafting_ids.add(row["item_id"])
        if gatherable:
            gathering_ids.add(row["item_id"])
        items.append(
            {
                "itemId": row["item_id"],
                "name": row["name"] or f"Item {row['item_id']}",
                "quality": row["quality"],
                "searchCategoryId": row["search_category_id"],
                "searchCategoryName": row["search_category_name"],
                "uiCategoryId": row["ui_category_id"],
                "uiCategoryName": row["ui_category_name"],
                "craftable": craftable,
                "craftTypeName": row["craft_type_name"],
                "gatherable": gatherable,
                "gatheringType": row["gathering_type"],
                "minListingPrice": row["min_listing_price"],
                "medianListingPrice": row["median_listing_price"],
                "averageSalePrice": average_price,
                "dailySaleVelocity": velocity,
                "estimatedDailyRevenue": daily_revenue,
                "latestUploadAt": row["latest_upload_at"],
                "status": status,
            }
        )

    payload = {
        "schemaVersion": 1,
        "kind": "market-items",
        "meta": {
            "scope": scope,
            "marketCollectedAt": market["collected_at"],
            "gameVersion": static["game_version"],
            "generatedAt": generated_at.isoformat(),
            "freshnessHours": freshness_hours,
            "homeWorldId": home_world_id,
            "source": "Universalis + FFXIV sqpack local",
        },
        "summary": {
            "rows": len(items),
            "gatheringItems": len(gathering_ids),
            "craftingItems": len(crafting_ids),
            "freshRows": fresh_rows,
        },
        "items": items,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return MarketItemsExportSummary(
        output_path=target.resolve(),
        scope=scope,
        rows=len(items),
        gathering_items=len(gathering_ids),
        crafting_items=len(crafting_ids),
    )


def _utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
