from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class HistoryExportSummary:
    output_path: Path
    scope: str
    series: int
    points: int


def conversion_history_key(
    currency_item_id: int,
    currency_quantity: int,
    reward_item_id: int,
    reward_quantity: int,
    reward_is_hq: bool,
) -> str:
    return ":".join(
        str(value)
        for value in (
            currency_item_id,
            currency_quantity,
            reward_item_id,
            reward_quantity,
            int(reward_is_hq),
        )
    )


def export_currency_history(
    database_path: Path | str,
    output_path: Path | str,
    *,
    scope: str,
) -> HistoryExportSummary:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT market.collected_at, value.currency_item_id, value.currency_name,
                   value.currency_quantity, value.reward_item_id, value.reward_name,
                   value.reward_quantity, value.reward_is_hq, value.market_unit_price,
                   value.net_gil_per_currency, value.daily_sale_velocity,
                   value.latest_upload_at, value.valuation_status
            FROM currency_market_valuation AS value
            JOIN currency_valuation_run AS run USING (valuation_run_id)
            JOIN market_source_snapshot AS market USING (market_snapshot_id)
            WHERE lower(run.scope) = lower(?)
              AND value.valuation_status IN ('FRESH', 'STALE')
            ORDER BY market.collected_at, value.net_gil_per_currency DESC,
                     value.daily_sale_velocity DESC
            """,
            (scope,),
        )
        series_by_key: dict[str, dict[str, Any]] = {}
        seen_points: set[tuple[str, str]] = set()
        point_count = 0
        for row in rows:
            key = conversion_history_key(
                row["currency_item_id"],
                row["currency_quantity"],
                row["reward_item_id"],
                row["reward_quantity"],
                bool(row["reward_is_hq"]),
            )
            point_signature = (key, row["collected_at"])
            if point_signature in seen_points:
                continue
            seen_points.add(point_signature)
            series = series_by_key.setdefault(
                key,
                {
                    "key": key,
                    "currencyItemId": row["currency_item_id"],
                    "currencyName": row["currency_name"],
                    "currencyQuantity": row["currency_quantity"],
                    "rewardItemId": row["reward_item_id"],
                    "rewardName": row["reward_name"],
                    "rewardQuantity": row["reward_quantity"],
                    "rewardIsHq": bool(row["reward_is_hq"]),
                    "points": [],
                },
            )
            series["points"].append(
                {
                    "marketCollectedAt": row["collected_at"],
                    "marketUnitPrice": row["market_unit_price"],
                    "netGilPerCurrency": row["net_gil_per_currency"],
                    "dailySaleVelocity": row["daily_sale_velocity"],
                    "latestUploadAt": row["latest_upload_at"],
                    "status": row["valuation_status"],
                }
            )
            point_count += 1
    finally:
        connection.close()

    payload = {
        "schemaVersion": 1,
        "kind": "currency-history",
        "meta": {
            "scope": scope,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        },
        "summary": {
            "series": len(series_by_key),
            "points": point_count,
        },
        "series": sorted(
            series_by_key.values(),
            key=lambda item: (
                item["currencyName"] or "",
                item["rewardName"] or "",
                item["key"],
            ),
        ),
    }
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return HistoryExportSummary(
        output_path=target_path.resolve(),
        scope=scope,
        series=len(series_by_key),
        points=point_count,
    )
