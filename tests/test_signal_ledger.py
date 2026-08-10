from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from gil_intelligence.publishing import export_signal_ledger
from gil_intelligence.storage.retention import prune_market_history


def test_signal_ledger_accumulates_observations_and_calculates_7d_return(tmp_path: Path) -> None:
    database_path = tmp_path / "ledger.sqlite3"
    output_path = tmp_path / "signals.json"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE market_source_snapshot (
            market_snapshot_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            collected_at TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO market_source_snapshot VALUES (?, 'Cactuar', ?)",
        [
            ("snapshot-1", "2026-08-01T00:00:00+00:00"),
            ("snapshot-2", "2026-08-09T00:00:00+00:00"),
        ],
    )
    connection.commit()
    connection.close()

    dashboard = {
        "conversions": [
            {
                "status": "FRESH",
                "currencyItemId": 1,
                "currencyName": "Test Token",
                "currencyQuantity": 2,
                "rewardItemId": 10,
                "rewardName": "Test Reward",
                "rewardQuantity": 1,
                "rewardIsHq": False,
                "netGilPerCurrency": 100.0,
                "marketUnitPrice": 210.0,
                "dailySaleVelocity": 12.0,
            }
        ]
    }
    opportunities = {"opportunities": []}

    def market(snapshot_id: str, observed_at: str) -> dict:
        return {
            "meta": {
                "scope": "Cactuar",
                "marketSnapshotId": snapshot_id,
                "marketCollectedAt": observed_at,
            },
            "items": [],
        }

    first = export_signal_ledger(
        database_path,
        output_path,
        dashboard=dashboard,
        market_items=market("snapshot-1", "2026-08-01T00:00:00+00:00"),
        opportunities=opportunities,
    )
    assert first.current_signals == 1
    assert first.observations == 1

    dashboard["conversions"][0]["netGilPerCurrency"] = 125.0
    second = export_signal_ledger(
        database_path,
        output_path,
        dashboard=dashboard,
        market_items=market("snapshot-2", "2026-08-09T00:00:00+00:00"),
        opportunities=opportunities,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    outcome = payload["signals"][0]["outcome"]

    assert second.observations == 2
    assert payload["summary"]["mature7d"] == 1
    assert outcome["observations"] == 2
    assert outcome["change"] == 0.25
    assert outcome["return7d"] == 0.25
    assert outcome["return30d"] is None

    prune_market_history(database_path, scope="Cactuar", keep_snapshots=1)
    connection = sqlite3.connect(database_path)
    retained_observations = connection.execute(
        "SELECT COUNT(*) FROM fact_signal_observation"
    ).fetchone()[0]
    connection.close()
    assert retained_observations == 2
