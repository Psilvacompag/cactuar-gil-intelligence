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

        raw_rows = connection.execute(
            """
            SELECT value.currency_item_id, value.currency_name,
                   currency_asset.icon_id AS currency_icon_id,
                   value.currency_quantity, value.reward_item_id,
                   value.reward_name, reward_asset.icon_id AS reward_icon_id,
                   value.reward_quantity, value.reward_is_hq,
                   value.market_unit_price, value.gross_gil_per_currency,
                   value.net_gil_per_currency, value.daily_sale_velocity,
                   value.latest_upload_at, value.valuation_status,
                   value.shop_id, shop.name AS shop_name, value.offer_index
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
              AND value.valuation_status IN ('FRESH', 'STALE')
            ORDER BY value.net_gil_per_currency DESC,
                     value.daily_sale_velocity DESC
            """,
            (selected_run,),
        )
        conversions = _deduplicate_conversions(raw_rows)
        listing_depth = detailed_listing_depth(
            connection,
            market_snapshot_id=run["market_snapshot_id"],
            home_world_id=home_world_id,
        )
        for conversion in conversions:
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
        currency_stats = _currency_stats(conversions)
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
            "directConversions": len(conversions),
            "currencies": len(currency_stats),
            "fresh": sum(item["status"] == "FRESH" for item in conversions),
            "stale": sum(item["status"] == "STALE" for item in conversions),
            "noMarketData": status_counts.get("NO_MARKET_DATA", 0),
            "notTradeable": status_counts.get("NOT_TRADEABLE", 0),
            "depthVerified": sum(item["listingDepth"] is not None for item in conversions),
        },
        "currencies": currency_stats,
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


def _deduplicate_conversions(rows: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        signature = (
            row["currency_item_id"],
            row["currency_quantity"],
            row["reward_item_id"],
            row["reward_quantity"],
            row["reward_is_hq"],
        )
        if signature in seen:
            continue
        seen.add(signature)
        result.append(
            {
                "currencyItemId": row["currency_item_id"],
                "currencyName": row["currency_name"] or f"Item {row['currency_item_id']}",
                "currencyIconId": row["currency_icon_id"],
                "currencyQuantity": row["currency_quantity"],
                "rewardItemId": row["reward_item_id"],
                "rewardName": row["reward_name"] or f"Item {row['reward_item_id']}",
                "rewardIconId": row["reward_icon_id"],
                "rewardQuantity": row["reward_quantity"],
                "rewardIsHq": bool(row["reward_is_hq"]),
                "marketUnitPrice": row["market_unit_price"],
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
    return result


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
                "bestNetGil": 0.0,
                "bestReward": None,
            },
        )
        current["conversionCount"] += 1
        if conversion["status"] == "FRESH":
            current["freshCount"] += 1
        net_gil = conversion["netGilPerCurrency"] or 0.0
        if net_gil > current["bestNetGil"]:
            current["bestNetGil"] = net_gil
            current["bestReward"] = conversion["rewardName"]
    return sorted(
        grouped.values(),
        key=lambda item: (item["bestNetGil"], item["freshCount"]),
        reverse=True,
    )
