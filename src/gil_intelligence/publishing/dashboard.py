from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .listing_depth import detailed_listing_depth, summarize_listing_depth


@dataclass(frozen=True, slots=True)
class DashboardExportSummary:
    output_path: Path
    valuation_run_id: str
    scope: str
    conversions: int
    currencies: int


def export_currency_dashboard(
    database_path: Path | str,
    output_path: Path | str,
    *,
    scope: str,
    valuation_run_id: str | None = None,
    home_world_id: int = 79,
) -> DashboardExportSummary:
    """Export a safe static payload for the browser-only dashboard."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        selected_run = valuation_run_id or _select_run(connection, scope)
        run = connection.execute(
            """
            SELECT run.*, market.collected_at AS market_collected_at,
                   market.requested_item_count, market.result_item_count,
                   market.failed_item_count, market.request_count,
                   market.collection_elapsed_seconds,
                   source.game_version
            FROM currency_valuation_run AS run
            JOIN market_source_snapshot AS market
                ON market.market_snapshot_id = run.market_snapshot_id
            JOIN source_snapshot AS source
                ON source.snapshot_id = run.static_snapshot_id
            WHERE run.valuation_run_id = ?
            """,
            (selected_run,),
        ).fetchone()
        if run is None:
            raise ValueError(f"Unknown valuation run: {selected_run}")
        if run["scope"].casefold() != scope.casefold():
            raise ValueError(f"Valuation run scope does not match {scope!r}")

        raw_rows = list(connection.execute(
            """
            SELECT value.currency_item_id, value.currency_name,
                   currency_asset.icon_id AS currency_icon_id,
                   value.currency_quantity, value.reward_item_id,
                   value.reward_name, reward_asset.icon_id AS reward_icon_id,
                   value.reward_quantity, value.reward_is_hq,
                   value.market_unit_price, value.net_total_gil,
                   value.gross_gil_per_currency,
                   value.net_gil_per_currency, value.daily_sale_velocity,
                   value.latest_upload_at, value.valuation_status,
                   value.shop_id, shop.name AS shop_name, value.offer_index,
                   value.cost_components_json
            FROM currency_market_valuation AS value
            LEFT JOIN dim_shop AS shop
                ON shop.snapshot_id = value.static_snapshot_id
                AND shop.shop_id = value.shop_id
            LEFT JOIN dim_asset AS currency_asset
                ON currency_asset.snapshot_id = value.static_snapshot_id
               AND currency_asset.item_id = value.currency_item_id
            LEFT JOIN dim_asset AS reward_asset
                ON reward_asset.snapshot_id = value.static_snapshot_id
               AND reward_asset.item_id = value.reward_item_id
            WHERE value.valuation_run_id = ?
              AND value.valuation_status <> 'NOT_TRADEABLE'
            ORDER BY CASE value.valuation_status
                         WHEN 'FRESH' THEN 0
                         WHEN 'STALE' THEN 1
                         WHEN 'NO_MARKET_DATA' THEN 2
                         WHEN 'NOT_TRADEABLE' THEN 3
                         ELSE 4
                     END,
                     value.net_gil_per_currency DESC,
                     value.daily_sale_velocity DESC
            """,
            (selected_run,),
        ))
        deduplication_audit: dict[str, int] = {}
        conversions = _deduplicate_conversions(raw_rows, audit=deduplication_audit)
        locations_by_shop = _shop_locations(
            connection,
            static_snapshot_id=run["static_snapshot_id"],
        )
        listing_depth = detailed_listing_depth(
            connection,
            market_snapshot_id=run["market_snapshot_id"],
            home_world_id=home_world_id,
        )
        for conversion in conversions:
            conversion["locations"] = locations_by_shop.get(conversion["shopId"], [])
            detail = listing_depth.get(
                (
                    conversion["rewardItemId"],
                    "HQ" if conversion["rewardIsHq"] else "NQ",
                )
            )
            conversion["listingDepth"] = summarize_listing_depth(
                detail,
                conversion["dailySaleVelocity"],
            )
        catalog_quality = _catalog_quality(
            conversions,
            locations_by_shop=locations_by_shop,
            duplicate_rows_removed=deduplication_audit.get("duplicateRowsRemoved", 0),
        )
        currency_stats = _currency_stats(conversions)
        market_conversions = [
            item for item in conversions if item["status"] in {"FRESH", "STALE"}
        ]
        market_routes = {
            (item["shopId"], item["offerIndex"]) for item in market_conversions
        }
        catalog_routes = {
            (item["shopId"], item["offerIndex"]) for item in conversions
        }
        status_counts = {
            row["valuation_status"]: row["count"]
            for row in connection.execute(
                """
                SELECT valuation_status, COUNT(*) AS count
                FROM currency_market_valuation
                WHERE valuation_run_id = ?
                GROUP BY valuation_status
                """,
                (selected_run,),
            )
        }
    finally:
        connection.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schemaVersion": 1,
        "meta": {
            "title": "FFXIV Gil Intelligence",
            "scope": run["scope"],
            "scopeLevel": run["market_scope_level"],
            "priceBasis": run["price_basis"],
            "feeRate": run["fee_rate"],
            "freshnessHours": run["freshness_hours"],
            "valuedAt": run["valued_at"],
            "marketCollectedAt": run["market_collected_at"],
            "gameVersion": run["game_version"],
            "generatedAt": generated_at,
            "requestCount": run["request_count"],
            "requestedItemCount": run["requested_item_count"],
            "resultItemCount": run["result_item_count"],
            "failedItemCount": run["failed_item_count"],
            "collectionElapsedSeconds": run["collection_elapsed_seconds"],
            "source": "Universalis + FFXIV sqpack local",
        },
        "summary": {
            "directConversions": len(market_routes),
            "catalogConversions": len(catalog_routes),
            "currencies": len(currency_stats),
            "fresh": status_counts.get("FRESH", 0),
            "stale": status_counts.get("STALE", 0),
            "noMarketData": status_counts.get("NO_MARKET_DATA", 0),
            "notTradeable": status_counts.get("NOT_TRADEABLE", 0),
            "depthVerified": sum(item["listingDepth"] is not None for item in conversions),
        },
        "currencies": currency_stats,
        "quality": catalog_quality,
        "conversions": conversions,
    }
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return DashboardExportSummary(
        output_path=target_path.resolve(),
        valuation_run_id=selected_run,
        scope=run["scope"],
        conversions=len(conversions),
        currencies=len(currency_stats),
    )


def _select_run(connection: sqlite3.Connection, scope: str) -> str:
    row = connection.execute(
        """
        SELECT valuation_run_id
        FROM currency_valuation_run
        WHERE lower(scope) = lower(?)
        ORDER BY valued_at DESC, created_at DESC
        LIMIT 1
        """,
        (scope,),
    ).fetchone()
    if row is None:
        raise ValueError(f"No valuation run is available for scope {scope!r}")
    return row[0]


def _deduplicate_conversions(
    rows: Any,
    *,
    audit: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    duplicate_rows_removed = 0
    for row in rows:
        try:
            components = json.loads(row["cost_components_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            components = []
        if not components:
            components = [{
                "itemId": row["currency_item_id"],
                "name": row["currency_name"] or f"Item {row['currency_item_id']}",
                "iconId": row["currency_icon_id"],
                "quantity": row["currency_quantity"],
            }]
        is_bundle = len(components) > 1
        for component in components:
            signature = (
                component["itemId"],
                component["quantity"],
                row["reward_item_id"],
                row["reward_quantity"],
                row["reward_is_hq"],
                tuple((cost["itemId"], cost["quantity"]) for cost in components),
            )
            if signature in seen:
                duplicate_rows_removed += 1
                continue
            seen.add(signature)
            result.append(
                {
                    "currencyItemId": component["itemId"],
                    "currencyName": component.get("name") or f"Item {component['itemId']}",
                    "currencyIconId": component.get("iconId"),
                    "currencyQuantity": component["quantity"],
                    "costComponents": components,
                    "isMultiCost": is_bundle,
                    "rewardItemId": row["reward_item_id"],
                    "rewardName": row["reward_name"] or f"Item {row['reward_item_id']}",
                    "rewardIconId": row["reward_icon_id"],
                    "rewardQuantity": row["reward_quantity"],
                    "rewardIsHq": bool(row["reward_is_hq"]),
                    "marketUnitPrice": row["market_unit_price"],
                    "netGilPerExchange": row["net_total_gil"],
                    "grossGilPerCurrency": row["gross_gil_per_currency"],
                    "netGilPerCurrency": row["net_gil_per_currency"],
                    "dailySaleVelocity": row["daily_sale_velocity"],
                    "latestUploadAt": row["latest_upload_at"],
                    "status": row["valuation_status"],
                    "shopId": row["shop_id"],
                    "shopName": row["shop_name"] or "SpecialShop",
                    "offerIndex": row["offer_index"],
                }
            )
    if audit is not None:
        audit["duplicateRowsRemoved"] = duplicate_rows_removed
    return result


def _catalog_quality(
    conversions: list[dict[str, Any]],
    *,
    locations_by_shop: dict[int, list[dict[str, Any]]],
    duplicate_rows_removed: int,
) -> dict[str, Any]:
    routes = {
        (int(item["shopId"]), int(item["offerIndex"]))
        for item in conversions
    }
    shop_ids = {shop_id for shop_id, _ in routes}
    located_shop_ids = {shop_id for shop_id in shop_ids if locations_by_shop.get(shop_id)}
    mapped_shop_ids = {
        shop_id
        for shop_id in located_shop_ids
        if any(location.get("mapAssetId") for location in locations_by_shop[shop_id])
    }
    expanded_shop_ids = {
        shop_id
        for shop_id in located_shop_ids
        if any(location.get("expansionName") for location in locations_by_shop[shop_id])
    }
    route_counts: dict[int, int] = {}
    names: dict[int, str] = {}
    for item in conversions:
        shop_id = int(item["shopId"])
        route_counts[shop_id] = route_counts.get(shop_id, 0) + 1
        names.setdefault(shop_id, str(item.get("shopName") or "SpecialShop"))
    missing = sorted(
        (
            {
                "shopId": shop_id,
                "shopName": names.get(shop_id) or "SpecialShop",
                "publishedConversions": route_counts.get(shop_id, 0),
            }
            for shop_id in shop_ids - located_shop_ids
        ),
        key=lambda item: (-item["publishedConversions"], item["shopId"]),
    )
    total_shops = len(shop_ids)
    return {
        "status": "COMPLETE" if len(located_shop_ids) == total_shops else "PARTIAL",
        "publishedRoutes": len(routes),
        "publishedShops": total_shops,
        "shopsWithLocation": len(located_shop_ids),
        "shopsWithMap": len(mapped_shop_ids),
        "shopsWithExpansion": len(expanded_shop_ids),
        "shopsWithoutLocation": total_shops - len(located_shop_ids),
        "locationCoveragePercent": (
            round(len(located_shop_ids) * 100 / total_shops, 1) if total_shops else 100.0
        ),
        "duplicateRowsRemoved": duplicate_rows_removed,
        "unlocatedShops": missing[:20],
    }


def _shop_locations(
    connection: sqlite3.Connection,
    *,
    static_snapshot_id: str,
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    rows = connection.execute(
        """
        SELECT shop_id, location_index, npc_id, npc_name, level_row_id,
               map_id, map_asset_id, place_name, region_name, territory_id,
               expansion_id, expansion_name,
               map_x, map_y, marker_left_percent, marker_top_percent,
               confidence
        FROM bridge_shop_location
        WHERE snapshot_id = ?
        ORDER BY shop_id, location_index
        """,
        (static_snapshot_id,),
    )
    for row in rows:
        grouped.setdefault(row["shop_id"], []).append(
            {
                "npcId": row["npc_id"],
                "npcName": row["npc_name"],
                "levelRowId": row["level_row_id"],
                "mapId": row["map_id"],
                "mapAssetId": row["map_asset_id"],
                "placeName": row["place_name"],
                "regionName": row["region_name"],
                "territoryId": row["territory_id"],
                "expansionId": row["expansion_id"],
                "expansionName": row["expansion_name"],
                "mapX": row["map_x"],
                "mapY": row["map_y"],
                "markerLeftPercent": row["marker_left_percent"],
                "markerTopPercent": row["marker_top_percent"],
                "confidence": row["confidence"],
            }
        )
    return grouped


def _currency_stats(conversions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for conversion in conversions:
        currency_id = conversion["currencyItemId"]
        current = grouped.setdefault(
            currency_id,
            {
                "itemId": currency_id,
                "name": conversion["currencyName"],
                "iconId": conversion.get("currencyIconId"),
                "conversionCount": 0,
                "freshCount": 0,
                "valuedCount": 0,
                "internalCount": 0,
                "unpricedCount": 0,
                "bundleCount": 0,
                "bestNetGil": None,
                "bestExchangeGil": None,
                "bestReward": None,
            },
        )
        current["conversionCount"] += 1
        if conversion["status"] == "FRESH":
            current["freshCount"] += 1
        if conversion["status"] in {"FRESH", "STALE"}:
            current["valuedCount"] += 1
        elif conversion["status"] == "NOT_TRADEABLE":
            current["internalCount"] += 1
        elif conversion["status"] == "NO_MARKET_DATA":
            current["unpricedCount"] += 1
        net_gil = conversion["netGilPerCurrency"]
        if conversion.get("isMultiCost"):
            current["bundleCount"] += 1
            exchange_gil = conversion.get("netGilPerExchange")
            if exchange_gil is not None and (
                current["bestExchangeGil"] is None
                or exchange_gil > current["bestExchangeGil"]
            ):
                current["bestExchangeGil"] = exchange_gil
        if net_gil is not None and (
            current["bestNetGil"] is None or net_gil > current["bestNetGil"]
        ):
            current["bestNetGil"] = net_gil
            current["bestReward"] = conversion["rewardName"]
        elif current["bestReward"] is None:
            current["bestReward"] = conversion["rewardName"]
    return sorted(
        grouped.values(),
        key=lambda item: (
            item["bestNetGil"] is None and item["bestExchangeGil"] is None,
            -(item["bestNetGil"] or item["bestExchangeGil"] or 0),
            -item["freshCount"],
            item["name"].casefold(),
        ),
    )
