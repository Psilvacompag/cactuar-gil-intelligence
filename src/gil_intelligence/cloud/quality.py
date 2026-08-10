from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from gil_intelligence.storage import MarketImportSummary


class DataQualityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RefreshQualityReport:
    coverage_ratio: float
    conversion_count: int
    fresh_count: int
    fresh_ratio: float
    failed_items: int
    stagnant_payload: bool
    warnings: tuple[str, ...]


def evaluate_refresh_quality(
    database_path: Path | str,
    dashboard_path: Path | str,
    market: MarketImportSummary,
    *,
    minimum_coverage_ratio: float = 0.98,
    minimum_conversions: int = 500,
    minimum_fresh_ratio: float = 0.5,
    maximum_failed_items: int = 100,
) -> RefreshQualityReport:
    payload = json.loads(Path(dashboard_path).read_text(encoding="utf-8"))
    summary = payload.get("summary", {})
    conversions = int(summary.get("directConversions", 0))
    fresh = int(summary.get("fresh", 0))
    coverage = market.result_items / market.requested_items if market.requested_items else 0.0
    fresh_ratio = fresh / conversions if conversions else 0.0

    connection = sqlite3.connect(database_path)
    try:
        hashes = connection.execute(
            """
            SELECT payload_sha256
            FROM market_source_snapshot
            WHERE lower(scope) = lower(?)
            ORDER BY collected_at DESC, market_snapshot_id DESC
            LIMIT 2
            """,
            (market.scope,),
        ).fetchall()
    finally:
        connection.close()
    stagnant = len(hashes) == 2 and hashes[0][0] == hashes[1][0]
    warnings = ("Universalis payload matches the previous snapshot",) if stagnant else ()

    failures: list[str] = []
    if coverage < minimum_coverage_ratio:
        failures.append(f"coverage {coverage:.3f} is below {minimum_coverage_ratio:.3f}")
    if market.failed_items > maximum_failed_items:
        failures.append(f"failed items {market.failed_items} exceed {maximum_failed_items}")
    if conversions < minimum_conversions:
        failures.append(f"conversions {conversions} are below {minimum_conversions}")
    if fresh_ratio < minimum_fresh_ratio:
        failures.append(f"fresh ratio {fresh_ratio:.3f} is below {minimum_fresh_ratio:.3f}")
    if failures:
        raise DataQualityError("; ".join(failures))

    return RefreshQualityReport(
        coverage_ratio=coverage,
        conversion_count=conversions,
        fresh_count=fresh,
        fresh_ratio=fresh_ratio,
        failed_items=market.failed_items,
        stagnant_payload=stagnant,
        warnings=warnings,
    )
