from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NORTH_AMERICA_DATA_CENTERS = {
    40: "Aether", 54: "Aether", 57: "Aether", 63: "Aether",
    65: "Aether", 73: "Aether", 79: "Aether", 99: "Aether",
    35: "Primal", 53: "Primal", 55: "Primal", 64: "Primal",
    77: "Primal", 78: "Primal", 93: "Primal", 95: "Primal",
    34: "Crystal", 37: "Crystal", 41: "Crystal", 62: "Crystal",
    74: "Crystal", 75: "Crystal", 81: "Crystal", 91: "Crystal",
    404: "Dynamis", 405: "Dynamis", 406: "Dynamis", 407: "Dynamis",
    408: "Dynamis", 409: "Dynamis", 410: "Dynamis", 411: "Dynamis",
}

NORTH_AMERICA_WORLD_NAMES = {
    34: "Brynhildr", 35: "Famfrit", 37: "Mateus", 40: "Jenova",
    41: "Zalera", 53: "Exodus", 54: "Faerie", 55: "Lamia", 57: "Siren",
    62: "Diabolos", 63: "Gilgamesh", 64: "Leviathan", 65: "Midgardsormr",
    73: "Adamantoise", 74: "Coeurl", 75: "Malboro", 77: "Ultros",
    78: "Behemoth", 79: "Cactuar", 81: "Goblin", 91: "Balmung",
    93: "Excalibur", 95: "Hyperion", 99: "Sargatanas", 404: "Marilith",
    405: "Seraph", 406: "Halicarnassus", 407: "Maduin", 408: "Cuchulainn",
    409: "Kraken", 410: "Rafflesia", 411: "Golem",
}

@dataclass(frozen=True, slots=True)
class OpportunitiesExportSummary:
    output_path: Path
    scope: str
    opportunities: int
    high_confidence: int
    medium_confidence: int
    stock_verified: int


def export_opportunities(
    database_path: Path | str,
    output_path: Path | str,
    *,
    scope: str,
    fee_rate: float = 0.05,
    price_stress: float = 0.20,
    freshness_hours: float = 12.0,
    home_world_id: int = 79,
) -> OpportunitiesExportSummary:
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
        current_rows = _pivoted_market_rows(
            connection,
            scope=scope,
            static_snapshot_id=static["snapshot_id"],
            market_snapshot_id=market["market_snapshot_id"],
            home_world_id=home_world_id,
        )
        history = _opportunity_history(connection, scope, fee_rate, price_stress, home_world_id)
        detailed = _detailed_listings(connection, market["market_snapshot_id"])
    finally:
        connection.close()

    generated_at = datetime.now(timezone.utc)
    opportunities: list[dict[str, Any]] = []
    for row in current_rows:
        source_price = row["source_price"]
        source_world_id = row["source_world_id"]
        velocity = row["daily_sale_velocity"]
        safe_price = _minimum_price(
            row["target_min_price"],
            row["target_median_price"],
            row["target_average_sale_price"],
        )
        source_upload_at = _utc_datetime(row["source_upload_at"])
        target_upload_at = _utc_datetime(row["target_upload_at"])
        if (
            source_price is None
            or source_price < 100
            or source_world_id is None
            or source_world_id == home_world_id
            or velocity is None
            or velocity < 5
            or safe_price is None
            or source_upload_at is None
            or target_upload_at is None
        ):
            continue
        source_age_hours = max(0.0, (generated_at - source_upload_at).total_seconds() / 3600)
        target_age_hours = max(0.0, (generated_at - target_upload_at).total_seconds() / 3600)
        age_hours = max(source_age_hours, target_age_hours)
        if age_hours > freshness_hours:
            continue
        conservative_sell_price = safe_price * (1 - price_stress)
        net_sell_price = conservative_sell_price * (1 - fee_rate)
        detail = detailed.get((row["item_id"], source_world_id, row["quality"]))
        stock_verified = detail is not None
        purchase_tiers: list[dict[str, int]] = []
        available_units: int | None = None
        detail_age_hours: float | None = None
        if detail is not None:
            detail_upload = _utc_datetime(detail["lastUploadAt"])
            if detail_upload is not None:
                detail_age_hours = max(
                    0.0,
                    (generated_at - detail_upload).total_seconds() / 3600,
                )
                age_hours = max(target_age_hours, detail_age_hours)
            maximum_buy_price = min(net_sell_price - 1000, net_sell_price / 1.20)
            eligible = [
                listing
                for listing in detail["listings"]
                if listing["pricePerUnit"] <= maximum_buy_price
            ]
            if not eligible:
                continue
            source_price = eligible[0]["pricePerUnit"]
            purchase_tiers = eligible
            available_units = sum(listing["quantity"] for listing in eligible)
        unit_profit = net_sell_price - source_price
        roi = unit_profit / source_price
        if unit_profit < 1000 or not 0.20 <= roi <= 2.0:
            continue

        history_key = (row["item_id"], row["quality"])
        samples = history.get(history_key, ())
        persistence = sum(samples) / len(samples) if samples else 0.0
        score_parts = _confidence_parts(roi, velocity, age_hours, freshness_hours, persistence)
        confidence_score = round(sum(score_parts.values()))
        confidence_band = (
            "HIGH" if confidence_score >= 75 else "MEDIUM" if confidence_score >= 55 else "WATCH"
        )
        recommended_quantity = max(1, min(20, math.floor(float(velocity) * 0.25)))
        purchase_cost = source_price * recommended_quantity
        average_purchase_price = source_price
        if stock_verified:
            recommended_quantity = min(recommended_quantity, available_units or 0)
            if recommended_quantity <= 0:
                continue
            purchase_cost, used_tiers = _tiered_purchase_cost(
                purchase_tiers,
                recommended_quantity,
            )
            average_purchase_price = purchase_cost / recommended_quantity
            unit_profit = net_sell_price - average_purchase_price
            roi = unit_profit / average_purchase_price
            purchase_tiers = used_tiers
        elif confidence_band == "HIGH":
            confidence_band = "MEDIUM"
        opportunities.append(
            {
                "itemId": row["item_id"],
                "name": row["name"] or f"Item {row['item_id']}",
                "iconId": row["icon_id"],
                "quality": row["quality"],
                "categoryName": row["search_category_name"] or row["ui_category_name"],
                "sourceWorldId": source_world_id,
                "sourceWorldName": NORTH_AMERICA_WORLD_NAMES.get(source_world_id, f"World {source_world_id}"),
                "sourceDataCenterName": NORTH_AMERICA_DATA_CENTERS.get(source_world_id, "North America"),
                "sourcePrice": source_price,
                "averagePurchasePrice": average_purchase_price,
                "cactuarMinPrice": row["target_min_price"],
                "cactuarMedianPrice": row["target_median_price"],
                "cactuarAverageSalePrice": row["target_average_sale_price"],
                "conservativeSellPrice": conservative_sell_price,
                "unitProfit": unit_profit,
                "roi": roi,
                "dailySaleVelocity": velocity,
                "recommendedQuantity": recommended_quantity,
                "estimatedPurchaseCost": purchase_cost,
                "estimatedTripProfit": net_sell_price * recommended_quantity - purchase_cost,
                "stockVerified": stock_verified,
                "stockStatus": "VERIFIED" if stock_verified else "UNVERIFIED",
                "availableUnits": available_units,
                "verifiedListingCount": len(purchase_tiers) if stock_verified else None,
                "purchaseTiers": purchase_tiers if stock_verified else [],
                "stockCheckedAt": detail["collectedAt"] if detail is not None else None,
                "stockDataAgeHours": detail_age_hours,
                "sourceUploadAt": row["source_upload_at"],
                "targetUploadAt": row["target_upload_at"],
                "dataAgeHours": age_hours,
                "persistenceRatio": persistence,
                "historySamples": len(samples),
                "confidenceScore": confidence_score,
                "confidenceBand": confidence_band,
                "scoreComponents": score_parts,
            }
        )

    opportunities.sort(
        key=lambda item: (
            item["confidenceScore"],
            item["estimatedTripProfit"],
            item["dailySaleVelocity"],
        ),
        reverse=True,
    )
    high = sum(item["confidenceBand"] == "HIGH" for item in opportunities)
    medium = sum(item["confidenceBand"] == "MEDIUM" for item in opportunities)
    verified = sum(item["stockVerified"] for item in opportunities)
    payload = {
        "schemaVersion": 1,
        "kind": "market-opportunities",
        "meta": {
            "scope": scope,
            "marketCollectedAt": market["collected_at"],
            "gameVersion": static["game_version"],
            "generatedAt": generated_at.isoformat(),
            "feeRate": fee_rate,
            "priceStress": price_stress,
            "freshnessHours": freshness_hours,
            "homeWorldId": home_world_id,
            "homeWorldName": NORTH_AMERICA_WORLD_NAMES.get(home_world_id, scope),
            "sourceScope": "North-America",
            "sourceScopeLevel": "REGION",
            "source": "Universalis aggregated market data",
        },
        "summary": {
            "opportunities": len(opportunities),
            "highConfidence": high,
            "mediumConfidence": medium,
            "watch": len(opportunities) - high - medium,
            "stockVerified": verified,
        },
        "opportunities": opportunities,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return OpportunitiesExportSummary(
        output_path=target.resolve(),
        scope=scope,
        opportunities=len(opportunities),
        high_confidence=high,
        medium_confidence=medium,
        stock_verified=verified,
    )


def _detailed_listings(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
) -> dict[tuple[int, int, str], dict[str, Any]]:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not {
        "detail_source_snapshot",
        "detail_item_snapshot",
        "fact_market_listing_snapshot",
    }.issubset(tables):
        return {}
    rows = connection.execute(
        """
        SELECT source.collected_at, item.item_id, item.world_id,
               item.last_upload_at, listing.quality, listing.price_per_unit,
               listing.quantity, listing.listing_rank
        FROM detail_source_snapshot AS source
        JOIN detail_item_snapshot AS item USING (detail_snapshot_id)
        LEFT JOIN fact_market_listing_snapshot AS listing
          ON listing.detail_snapshot_id = item.detail_snapshot_id
         AND listing.item_id = item.item_id
         AND listing.world_id = item.world_id
        WHERE source.market_snapshot_id = ?
        ORDER BY item.item_id, item.world_id, listing.quality,
                 listing.price_per_unit, listing.listing_rank
        """,
        (market_snapshot_id,),
    ).fetchall()
    result: dict[tuple[int, int, str], dict[str, Any]] = {}
    for row in rows:
        for quality in ("NQ", "HQ"):
            result.setdefault(
                (row["item_id"], row["world_id"], quality),
                {
                    "collectedAt": row["collected_at"],
                    "lastUploadAt": row["last_upload_at"],
                    "listings": [],
                },
            )
        if row["quality"] is None:
            continue
        document = result[(row["item_id"], row["world_id"], row["quality"])]
        document["listings"].append(
            {
                "pricePerUnit": row["price_per_unit"],
                "quantity": row["quantity"],
            }
        )
    return result


def _tiered_purchase_cost(
    tiers: list[dict[str, int]],
    quantity: int,
) -> tuple[float, list[dict[str, int]]]:
    remaining = quantity
    total = 0.0
    used: list[dict[str, int]] = []
    for tier in tiers:
        take = min(remaining, tier["quantity"])
        if take <= 0:
            continue
        total += take * tier["pricePerUnit"]
        used.append({"pricePerUnit": tier["pricePerUnit"], "quantity": take})
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise ValueError("Detailed listing tiers did not cover the requested quantity")
    return total, used


def _pivoted_market_rows(
    connection: sqlite3.Connection,
    *,
    scope: str,
    static_snapshot_id: str,
    market_snapshot_id: str,
    home_world_id: int,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        WITH pivoted AS (
        SELECT asset.item_id, asset.name, asset.icon_id, asset.search_category_name,
               asset.ui_category_name, aggregate.quality,
               MAX(CASE WHEN aggregate.scope_level = 'WORLD'
                        THEN aggregate.min_listing_price END) AS target_min_price,
               MAX(CASE WHEN aggregate.scope_level = 'WORLD'
                        THEN aggregate.median_listing_price END) AS target_median_price,
               MAX(CASE WHEN aggregate.scope_level = 'WORLD'
                        THEN aggregate.average_sale_price END) AS target_average_sale_price,
               MAX(CASE WHEN aggregate.scope_level = 'WORLD'
                        THEN aggregate.daily_sale_velocity END) AS daily_sale_velocity,
               MAX(CASE WHEN aggregate.scope_level = 'REGION'
                        THEN aggregate.min_listing_price END) AS source_price,
               MAX(CASE WHEN aggregate.scope_level = 'REGION'
                        THEN aggregate.min_listing_world_id END) AS source_world_id
        FROM dim_asset AS asset
        JOIN fact_market_aggregate_snapshot AS aggregate
          ON aggregate.market_snapshot_id = ?
         AND aggregate.item_id = asset.item_id
         AND aggregate.scope_level IN ('WORLD', 'REGION')
        WHERE asset.snapshot_id = ?
          AND asset.marketable_candidate = 1
        GROUP BY asset.item_id, asset.name, asset.icon_id, asset.search_category_name,
                 asset.ui_category_name, aggregate.quality
        )
        SELECT pivoted.*,
               MAX(CASE WHEN freshness.world_id = pivoted.source_world_id
                        THEN freshness.uploaded_at END) AS source_upload_at,
               MAX(CASE WHEN freshness.world_id = ?
                        THEN freshness.uploaded_at END) AS target_upload_at
        FROM pivoted
        LEFT JOIN fact_data_freshness AS freshness
          ON freshness.market_snapshot_id = ?
         AND freshness.item_id = pivoted.item_id
        GROUP BY pivoted.item_id, pivoted.name, pivoted.icon_id, pivoted.search_category_name,
                 pivoted.ui_category_name, pivoted.quality,
                 pivoted.target_min_price, pivoted.target_median_price,
                 pivoted.target_average_sale_price, pivoted.daily_sale_velocity,
                 pivoted.source_price, pivoted.source_world_id
        """,
        (
            market_snapshot_id,
            static_snapshot_id,
            home_world_id,
            market_snapshot_id,
        ),
    ).fetchall()


def _opportunity_history(
    connection: sqlite3.Connection,
    scope: str,
    fee_rate: float,
    price_stress: float,
    home_world_id: int,
) -> dict[tuple[int, str], tuple[bool, ...]]:
    rows = connection.execute(
        """
        SELECT aggregate.market_snapshot_id, aggregate.item_id, aggregate.quality,
               aggregate.scope_level, aggregate.min_listing_price,
               aggregate.median_listing_price, aggregate.average_sale_price,
               aggregate.min_listing_world_id, source.collected_at
        FROM fact_market_aggregate_snapshot AS aggregate
        JOIN market_source_snapshot AS source USING (market_snapshot_id)
        WHERE lower(source.scope) = lower(?)
          AND aggregate.scope_level IN ('WORLD', 'REGION')
        ORDER BY source.collected_at, aggregate.market_snapshot_id
        """,
        (scope,),
    )
    grouped: dict[tuple[str, int, str], dict[str, sqlite3.Row]] = {}
    order: list[str] = []
    for row in rows:
        key = (row["market_snapshot_id"], row["item_id"], row["quality"])
        grouped.setdefault(key, {})[row["scope_level"]] = row
        if row["market_snapshot_id"] not in order:
            order.append(row["market_snapshot_id"])
    order = order[-5:]
    history: dict[tuple[int, str], list[bool]] = {}
    for (snapshot_id, item_id, quality), levels in grouped.items():
        if snapshot_id not in order or "WORLD" not in levels or "REGION" not in levels:
            continue
        world = levels["WORLD"]
        region = levels["REGION"]
        safe_price = _minimum_price(
            world["min_listing_price"],
            world["median_listing_price"],
            world["average_sale_price"],
        )
        buy_price = region["min_listing_price"]
        buy_world = region["min_listing_world_id"]
        if safe_price is None or buy_price is None or buy_price <= 0 or buy_world is None:
            continue
        profit = safe_price * (1 - price_stress) * (1 - fee_rate) - buy_price
        roi = profit / buy_price
        history.setdefault((item_id, quality), []).append(
            buy_world != home_world_id and profit >= 1000 and 0.20 <= roi <= 2.0
        )
    return {key: tuple(values) for key, values in history.items()}


def _confidence_parts(
    roi: float,
    velocity: float,
    age_hours: float,
    freshness_hours: float,
    persistence: float,
) -> dict[str, float]:
    margin = min(30.0, 10.0 + roi * 20.0)
    velocity_scale = max(0.0, min(1.0, math.log(max(velocity, 5) / 5) / math.log(10)))
    liquidity = 10.0 + velocity_scale * 15.0
    freshness = max(0.0, 20.0 * (1 - age_hours / freshness_hours))
    persistence_score = 25.0 * persistence
    return {
        "margin": round(margin, 1),
        "liquidity": round(liquidity, 1),
        "freshness": round(freshness, 1),
        "persistence": round(persistence_score, 1),
    }


def _minimum_price(*values: float | None) -> float | None:
    present = [float(value) for value in values if value is not None and value > 0]
    return min(present) if present else None


def _utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
