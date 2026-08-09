from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gil_intelligence.storage import import_static_snapshot


def example_snapshot() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "source": "sqpack",
        "gameVersion": "2026.08.05.0000.0000",
        "extractedAt": "2026-08-09T20:00:00+00:00",
        "assets": [
            {"itemId": 28, "name": "Allagan Tomestone of Poetics", "marketableCandidate": False},
            {"itemId": 100, "name": "Example Reward", "marketableCandidate": True},
        ],
        "shops": [{"shopId": 10, "name": "Example Shop", "useCurrencyType": 16}],
        "offers": [
            {
                "shopId": 10,
                "offerIndex": 2,
                "sourceSubrowKey": "10:2",
                "parseStatus": "PARSED",
            }
        ],
        "costs": [
            {
                "shopId": 10,
                "offerIndex": 2,
                "costIndex": 0,
                "rawItemId": 8,
                "itemId": 28,
                "quantity": 20,
                "costType": 0,
            }
        ],
        "rewards": [
            {
                "shopId": 10,
                "offerIndex": 2,
                "rewardIndex": 0,
                "itemId": 100,
                "quantity": 1,
                "isHq": True,
            }
        ],
        "requirements": [
            {
                "shopId": 10,
                "offerIndex": None,
                "requirementType": "QUEST",
                "requirementValue": 5,
            }
        ],
        "coverage": {"sourceRows": 1, "offersEmitted": 1, "rowsIgnored": 0, "rowsFailed": 0},
    }


class StaticCatalogImportTests(unittest.TestCase):
    def test_imports_normalized_tables_and_is_idempotent_per_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "snapshot.json"
            database_path = root / "catalog.sqlite3"
            snapshot_path.write_text(json.dumps(example_snapshot()), encoding="utf-8")

            first = import_static_snapshot(snapshot_path, database_path)
            second = import_static_snapshot(snapshot_path, database_path)

            self.assertEqual(first.snapshot_id, "sqpack:2026.08.05.0000.0000:schema-1")
            self.assertEqual(first, second)
            connection = sqlite3.connect(database_path)
            try:
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "source_snapshot",
                        "dim_asset",
                        "dim_shop",
                        "dim_shop_offer",
                        "bridge_offer_cost",
                        "bridge_offer_reward",
                        "bridge_offer_requirement",
                        "shop_coverage_audit",
                    )
                }
                cost = connection.execute(
                    "SELECT raw_item_id, item_id, quantity FROM bridge_offer_cost"
                ).fetchone()
                reward = connection.execute(
                    "SELECT item_id, quantity, is_hq FROM bridge_offer_reward"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(
                counts,
                {
                    "source_snapshot": 1,
                    "dim_asset": 2,
                    "dim_shop": 1,
                    "dim_shop_offer": 1,
                    "bridge_offer_cost": 1,
                    "bridge_offer_reward": 1,
                    "bridge_offer_requirement": 1,
                    "shop_coverage_audit": 1,
                },
            )
            self.assertEqual(cost, (8, 28, 20))
            self.assertEqual(reward, (100, 1, 1))

    def test_rejects_unknown_snapshot_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = example_snapshot()
            payload["schemaVersion"] = 99
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Unsupported snapshot schema 99"):
                import_static_snapshot(snapshot_path, root / "catalog.sqlite3")

    def test_rejects_non_positive_component_quantity_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = example_snapshot()
            payload["costs"][0]["quantity"] = 0
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"costs\[0\]\.quantity must be a positive integer"):
                import_static_snapshot(snapshot_path, root / "catalog.sqlite3")

            self.assertFalse((root / "catalog.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
