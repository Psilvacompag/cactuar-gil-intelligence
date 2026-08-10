from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketHistoryExportSummary:
    output_path: Path
    scope: str
    snapshots: int
    series: int
    points: int


def market_history_series(
    connection: sqlite3.Connection,
    *,
    scope: str,
    static_snapshot_id: str,
    max_snapshots: int = 14,
) -> tuple[list[str], dict[tuple[int, str], dict[str, Any]]]:
    snapshot_rows = connection.execute(
        """
        SELECT market_snapshot_id, collected_at
        FROM market_source_snapshot
        WHERE lower(scope) = lower(?)
        ORDER BY collected_at DESC, market_snapshot_id DESC
        LIMIT ?
        """,
        (scope, max_snapshots),
    ).fetchall()
    snapshot_rows = list(reversed(snapshot_rows))
    snapshot_ids = [row["market_snapshot_id"] for row in snapshot_rows]
    if not snapshot_ids:
        return [], {}
    placeholders = ",".join("?" for _ in snapshot_ids)
    rows = connection.execute(
        f"""
        SELECT aggregate.market_snapshot_id, source.collected_at,
               aggregate.item_id, aggregate.quality,
               aggregate.min_listing_price, aggregate.median_listing_price,
               aggregate.average_sale_price, aggregate.daily_sale_velocity
        FROM fact_market_aggregate_snapshot AS aggregate
        JOIN market_source_snapshot AS source USING (market_snapshot_id)
        JOIN dim_asset AS asset
          ON asset.snapshot_id = ?
         AND asset.item_id = aggregate.item_id
        WHERE aggregate.market_snapshot_id IN ({placeholders})
          AND aggregate.scope_level = 'WORLD'
          AND (
              asset.craftable = 1
              OR asset.gatherable = 1
              OR asset.item_id BETWEEN 41757 AND 41769
          )
          AND EXISTS (
              SELECT 1
              FROM fact_market_aggregate_snapshot AS latest
              WHERE latest.market_snapshot_id = ?
                AND latest.item_id = aggregate.item_id
                AND latest.quality = aggregate.quality
                AND latest.scope_level = 'WORLD'
                AND latest.daily_sale_velocity > 0
          )
        ORDER BY source.collected_at, aggregate.market_snapshot_id,
                 aggregate.item_id, aggregate.quality
        """,
        (static_snapshot_id, *snapshot_ids, snapshot_ids[-1]),
    ).fetchall()
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in rows:
        average_price = row["average_sale_price"]
        velocity = row["daily_sale_velocity"]
        grouped.setdefault((row["item_id"], row["quality"]), []).append(
            {
                "marketSnapshotId": row["market_snapshot_id"],
                "collectedAt": row["collected_at"],
                "minListingPrice": row["min_listing_price"],
                "medianListingPrice": row["median_listing_price"],
                "averageSalePrice": average_price,
                "dailySaleVelocity": velocity,
                "estimatedDailyRevenue": (
                    float(average_price) * float(velocity)
                    if average_price is not None and velocity is not None
                    else None
                ),
            }
        )
    series = {
        key: {"points": points, "trend": summarize_market_points(points)}
        for key, points in grouped.items()
    }
    return [row["collected_at"] for row in snapshot_rows], series


def summarize_market_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    prices = [float(point["averageSalePrice"]) for point in points if point["averageSalePrice"]]
    velocities = [
        float(point["dailySaleVelocity"])
        for point in points
        if point["dailySaleVelocity"] is not None
    ]
    price_change = _change_ratio(prices)
    velocity_change = _change_ratio(velocities)
    volatility = statistics.pstdev(prices) / statistics.fmean(prices) if len(prices) >= 2 else None
    if len(points) < 2:
        signal = "NEW"
    elif velocity_change is not None and velocity_change >= 0.20:
        signal = "DEMAND_UP"
    elif velocity_change is not None and velocity_change <= -0.20:
        signal = "COOLING"
    elif price_change is not None and price_change >= 0.15:
        signal = "PRICE_UP"
    else:
        signal = "STABLE"
    stability = (
        "UNKNOWN"
        if volatility is None
        else "HIGH"
        if volatility <= 0.10
        else "MEDIUM"
        if volatility <= 0.25
        else "LOW"
    )
    return {
        "historyPoints": len(points),
        "priceChangeRatio": price_change,
        "velocityChangeRatio": velocity_change,
        "priceVolatility": volatility,
        "stability": stability,
        "signal": signal,
    }


def export_market_history(
    database_path: Path | str,
    output_path: Path | str,
    *,
    scope: str,
    max_snapshots: int = 14,
) -> MarketHistoryExportSummary:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
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
        snapshots, grouped = market_history_series(
            connection,
            scope=scope,
            static_snapshot_id=static["snapshot_id"],
            max_snapshots=max_snapshots,
        )
    finally:
        connection.close()
    series = [
        {
            "key": f"{item_id}:{quality}",
            "itemId": item_id,
            "quality": quality,
            "trend": document["trend"],
            "points": document["points"],
        }
        for (item_id, quality), document in sorted(grouped.items())
    ]
    payload = {
        "schemaVersion": 1,
        "kind": "market-history",
        "meta": {
            "scope": scope,
            "gameVersion": static["game_version"],
            "generatedSnapshots": len(snapshots),
            "firstCollectedAt": snapshots[0] if snapshots else None,
            "marketCollectedAt": snapshots[-1] if snapshots else None,
        },
        "summary": {
            "snapshots": len(snapshots),
            "series": len(series),
            "points": sum(len(document["points"]) for document in grouped.values()),
        },
        "series": series,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return MarketHistoryExportSummary(
        output_path=target.resolve(),
        scope=scope,
        snapshots=len(snapshots),
        series=len(series),
        points=payload["summary"]["points"],
    )


def _change_ratio(values: list[float]) -> float | None:
    if len(values) < 2 or values[0] <= 0:
        return None
    return (values[-1] - values[0]) / values[0]
