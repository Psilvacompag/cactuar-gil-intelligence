from __future__ import annotations

import sqlite3
from typing import Any


def detailed_listing_depth(
    connection: sqlite3.Connection,
    *,
    market_snapshot_id: str,
    home_world_id: int,
) -> dict[tuple[int, str], dict[str, Any]]:
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if not {
        "detail_source_snapshot",
        "detail_item_snapshot",
        "fact_market_listing_snapshot",
    }.issubset(tables):
        return {}
    rows = connection.execute(
        """
        SELECT source.collected_at, item.last_upload_at, listing.item_id,
               listing.quality, listing.price_per_unit, listing.quantity,
               listing.listing_rank
        FROM detail_source_snapshot AS source
        JOIN detail_item_snapshot AS item USING (detail_snapshot_id)
        JOIN fact_market_listing_snapshot AS listing
          ON listing.detail_snapshot_id = item.detail_snapshot_id
         AND listing.item_id = item.item_id
         AND listing.world_id = item.world_id
        WHERE source.market_snapshot_id = ?
          AND item.world_id = ?
        ORDER BY listing.item_id, listing.quality,
                 listing.price_per_unit, listing.listing_rank
        """,
        (market_snapshot_id, home_world_id),
    )
    result: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        document = result.setdefault(
            (row["item_id"], row["quality"]),
            {
                "collectedAt": row["collected_at"],
                "lastUploadAt": row["last_upload_at"],
                "listings": [],
            },
        )
        document["listings"].append(
            {
                "pricePerUnit": row["price_per_unit"],
                "quantity": row["quantity"],
            }
        )
    return result


def summarize_listing_depth(
    detail: dict[str, Any] | None,
    daily_sale_velocity: float | None,
) -> dict[str, Any] | None:
    if detail is None or not detail["listings"]:
        return None
    listings = detail["listings"]
    floor_price = float(listings[0]["pricePerUnit"])
    near_floor_units = sum(
        int(listing["quantity"])
        for listing in listings
        if float(listing["pricePerUnit"]) <= floor_price * 1.10
    )
    units_observed = sum(int(listing["quantity"]) for listing in listings)
    target_units = min(20, units_observed)
    remaining = target_units
    weighted_total = 0.0
    used_tiers: list[dict[str, int]] = []
    for listing in listings:
        take = min(remaining, int(listing["quantity"]))
        if take <= 0:
            continue
        weighted_total += take * float(listing["pricePerUnit"])
        used_tiers.append(
            {"pricePerUnit": int(listing["pricePerUnit"]), "quantity": take}
        )
        remaining -= take
        if remaining == 0:
            break
    velocity = float(daily_sale_velocity) if daily_sale_velocity is not None else None
    supply_days = near_floor_units / velocity if velocity and velocity > 0 else None
    pressure = (
        "UNKNOWN"
        if supply_days is None
        else "HIGH"
        if supply_days >= 1.0
        else "MEDIUM"
        if supply_days >= 0.25
        else "LOW"
    )
    return {
        "verified": True,
        "checkedAt": detail["collectedAt"],
        "lastUploadAt": detail["lastUploadAt"],
        "listingCount": len(listings),
        "unitsObserved": units_observed,
        "floorPrice": floor_price,
        "nearFloorThreshold": floor_price * 1.10,
        "nearFloorUnits": near_floor_units,
        "nearFloorSupplyDays": supply_days,
        "pressure": pressure,
        "weightedPriceForUnits": weighted_total / target_units,
        "weightedUnitCount": target_units,
        "tiers": used_tiers,
    }
