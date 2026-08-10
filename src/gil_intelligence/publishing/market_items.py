from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .market_history import market_history_series


@dataclass(frozen=True, slots=True)
class MarketItemsExportSummary:
    output_path: Path
    scope: str
    rows: int
    gathering_items: int
    crafting_items: int
    profitable_crafts: int


def export_market_items(
    database_path: Path | str,
    output_path: Path | str,
    *,
    scope: str,
    freshness_hours: float = 24.0,
    home_world_id: int = 79,
    fee_rate: float = 0.05,
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
        history_snapshots, history = market_history_series(
            connection,
            scope=scope,
            static_snapshot_id=static["snapshot_id"],
        )
        recipes = _recipe_options(
            connection,
            static_snapshot_id=static["snapshot_id"],
            market_snapshot_id=market["market_snapshot_id"],
        )
    finally:
        connection.close()

    generated_at = datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    gathering_ids: set[int] = set()
    crafting_ids: set[int] = set()
    fresh_rows = 0
    profitable_ids: set[int] = set()
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
        trend = history.get((row["item_id"], row["quality"]), {}).get("trend", {})
        recipe = recipes.get(row["item_id"])
        recipe_financials: dict[str, Any] | None = None
        sale_prices = [
            float(value)
            for value in (
                row["min_listing_price"],
                row["median_listing_price"],
                average_price,
            )
            if value is not None and value > 0
        ]
        if recipe is not None and sale_prices:
            conservative_sale_price = min(sale_prices) * 0.80
            net_revenue = conservative_sale_price * recipe["resultQuantity"] * (1 - fee_rate)
            profit_per_craft = net_revenue - recipe["estimatedMaterialCost"]
            profit_per_unit = profit_per_craft / recipe["resultQuantity"]
            roi = (
                profit_per_craft / recipe["estimatedMaterialCost"]
                if recipe["estimatedMaterialCost"] > 0
                else None
            )
            daily_profit = float(velocity) * profit_per_unit if velocity is not None else None
            confidence = (
                "LOW"
                if velocity is None or velocity < 1
                else "LOW"
                if trend.get("historyPoints", 0) >= 2
                and trend.get("priceVolatility") is not None
                and trend["priceVolatility"] > 0.50
                else "HIGH"
                if velocity >= 5
                and trend.get("historyPoints", 0) >= 3
                and trend.get("stability") in {"HIGH", "MEDIUM"}
                else "MEDIUM"
            )
            if profit_per_craft > 0 and confidence != "LOW":
                profitable_ids.add(row["item_id"])
            recipe_financials = {
                **recipe,
                "netRevenuePerCraft": net_revenue,
                "conservativeSalePrice": conservative_sale_price,
                "profitPerCraft": profit_per_craft,
                "profitPerUnit": profit_per_unit,
                "roi": roi,
                "estimatedDailyProfit": daily_profit,
                "confidence": confidence,
            }
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
                "trend": trend,
                "recipe": recipe_financials,
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
            "feeRate": fee_rate,
            "historySnapshots": len(history_snapshots),
            "source": "Universalis + FFXIV sqpack local",
        },
        "summary": {
            "rows": len(items),
            "gatheringItems": len(gathering_ids),
            "craftingItems": len(crafting_ids),
            "freshRows": fresh_rows,
            "profitableCrafts": len(profitable_ids),
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
        profitable_crafts=len(profitable_ids),
    )


def _recipe_options(
    connection: sqlite3.Connection,
    *,
    static_snapshot_id: str,
    market_snapshot_id: str,
) -> dict[int, dict[str, Any]]:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not {"dim_recipe", "bridge_recipe_ingredient"}.issubset(tables):
        return {}
    price_rows = connection.execute(
        """
        SELECT asset.item_id, asset.name, asset.gatherable,
               market.min_listing_price, market.average_sale_price
        FROM dim_asset AS asset
        LEFT JOIN fact_market_aggregate_snapshot AS market
          ON market.market_snapshot_id = ?
         AND market.item_id = asset.item_id
         AND market.quality = 'NQ'
         AND market.scope_level = 'WORLD'
        WHERE asset.snapshot_id = ?
        """,
        (market_snapshot_id, static_snapshot_id),
    ).fetchall()
    item_info: dict[int, dict[str, Any]] = {}
    for row in price_rows:
        prices = [
            float(value)
            for value in (row["min_listing_price"], row["average_sale_price"])
            if value is not None and value > 0
        ]
        item_info[row["item_id"]] = {
            "name": row["name"] or f"Item {row['item_id']}",
            "gatherable": bool(row["gatherable"]),
            "unitPrice": max(prices) if prices else None,
        }
    recipe_rows = connection.execute(
        """
        SELECT recipe.recipe_id, recipe.result_item_id, recipe.result_quantity,
               recipe.craft_type_name, recipe.can_hq, recipe.is_expert,
               ingredient.ingredient_index, ingredient.item_id, ingredient.quantity
        FROM dim_recipe AS recipe
        LEFT JOIN bridge_recipe_ingredient AS ingredient
          ON ingredient.snapshot_id = recipe.snapshot_id
         AND ingredient.recipe_id = recipe.recipe_id
        WHERE recipe.snapshot_id = ?
        ORDER BY recipe.recipe_id, ingredient.ingredient_index
        """,
        (static_snapshot_id,),
    ).fetchall()
    by_recipe: dict[int, dict[str, Any]] = {}
    for row in recipe_rows:
        document = by_recipe.setdefault(
            row["recipe_id"],
            {
                "recipeId": row["recipe_id"],
                "resultItemId": row["result_item_id"],
                "resultQuantity": row["result_quantity"],
                "craftTypeName": row["craft_type_name"],
                "canHq": bool(row["can_hq"]),
                "isExpert": bool(row["is_expert"]),
                "ingredients": [],
            },
        )
        if row["item_id"] is None:
            continue
        info = item_info.get(row["item_id"], {})
        unit_price = info.get("unitPrice")
        document["ingredients"].append(
            {
                "itemId": row["item_id"],
                "name": info.get("name", f"Item {row['item_id']}"),
                "quantity": row["quantity"],
                "unitPrice": unit_price,
                "subtotal": unit_price * row["quantity"] if unit_price is not None else None,
                "gatherable": bool(info.get("gatherable", False)),
            }
        )
    complete_by_result: dict[int, list[dict[str, Any]]] = {}
    for document in by_recipe.values():
        if any(ingredient["unitPrice"] is None for ingredient in document["ingredients"]):
            continue
        material_cost = sum(ingredient["subtotal"] for ingredient in document["ingredients"])
        complete = {**document, "estimatedMaterialCost": material_cost}
        complete_by_result.setdefault(document["resultItemId"], []).append(complete)
    return {
        item_id: min(options, key=lambda option: option["estimatedMaterialCost"])
        for item_id, options in complete_by_result.items()
    }


def _utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
