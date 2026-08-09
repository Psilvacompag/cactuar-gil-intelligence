from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MarketRetentionSummary:
    scope: str
    kept_snapshots: int
    removed_snapshots: int


def prune_market_history(
    database_path: Path | str,
    *,
    scope: str,
    keep_snapshots: int,
) -> MarketRetentionSummary:
    """Keep recent snapshots for one scope and let SQLite reuse deleted pages."""
    if keep_snapshots < 1:
        raise ValueError("keep_snapshots must be positive")
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        snapshot_ids = [
            row[0]
            for row in connection.execute(
                """
                SELECT market_snapshot_id
                FROM market_source_snapshot
                WHERE lower(scope) = lower(?)
                ORDER BY collected_at DESC, market_snapshot_id DESC
                """,
                (scope,),
            )
        ]
        removed = snapshot_ids[keep_snapshots:]
        if removed:
            with connection:
                connection.executemany(
                    "DELETE FROM market_source_snapshot WHERE market_snapshot_id = ?",
                    ((snapshot_id,) for snapshot_id in removed),
                )
    finally:
        connection.close()
    return MarketRetentionSummary(
        scope=scope,
        kept_snapshots=min(len(snapshot_ids), keep_snapshots),
        removed_snapshots=len(removed),
    )
