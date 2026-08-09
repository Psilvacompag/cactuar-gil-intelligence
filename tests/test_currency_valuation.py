from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gil_intelligence.storage import import_static_snapshot, import_universalis_aggregates
from gil_intelligence.publishing import export_currency_dashboard
from gil_intelligence.valuation import build_currency_valuations, get_top_currency_conversions

from test_static_catalog import example_snapshot


class CurrencyValuationTests(unittest.TestCase):
    def test_values_simple_currency_offer_with_fee_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "catalog.sqlite3"
            static_payload = example_snapshot()
            static_payload["assets"][1]["itemId"] = 2
            static_payload["assets"][1]["name"] = "Fire Shard"
            static_payload["rewards"][0].update(
                {"itemId": 2, "quantity": 2, "isHq": False}
            )
            snapshot_path = root / "static.json"
            snapshot_path.write_text(json.dumps(static_payload), encoding="utf-8")
            import_static_snapshot(snapshot_path, database_path)
            import_universalis_aggregates(
                {
                    "results": [
                        {
                            "itemId": 2,
                            "nq": {
                                "minListing": {
                                    "world": {"price": 80, "worldId": 79},
                                    "dc": {"price": 100, "worldId": 57},
                                },
                                "medianListing": {
                                    "world": {"price": 90},
                                    "dc": {"price": 110},
                                },
                                "recentPurchase": {},
                                "averageSalePrice": {
                                    "world": {"price": 75},
                                    "dc": {"price": 90},
                                },
                                "dailySaleVelocity": {
                                    "world": {"quantity": 3},
                                    "dc": {"quantity": 12},
                                },
                            },
                            "hq": {},
                            "worldUploadTimes": [
                                {"worldId": 57, "timestamp": 1786309130257}
                            ],
                        }
                    ],
                    "failedItems": [],
                },
                database_path,
                scope="Cactuar",
                collected_at="2026-08-09T21:06:59Z",
                requested_items=1,
            )

            summary = build_currency_valuations(
                database_path,
                scope="Cactuar",
                fee_rate=0.05,
                as_of=datetime(2026, 8, 9, 21, 7, tzinfo=timezone.utc),
            )
            top = get_top_currency_conversions(database_path, summary.valuation_run_id)

            self.assertEqual(summary.eligible_offers, 1)
            self.assertEqual(summary.market_scope_level, "WORLD")
            self.assertEqual(summary.valued_offers, 1)
            self.assertEqual(summary.fresh_offers, 1)
            self.assertEqual(summary.valued_at, "2026-08-09T21:07:00+00:00")
            self.assertEqual(top[0]["currency_name"], "Allagan Tomestone of Poetics")
            self.assertEqual(top[0]["reward_name"], "Fire Shard")
            self.assertEqual(top[0]["market_unit_price"], 80.0)
            self.assertAlmostEqual(top[0]["net_gil_per_currency"], 7.6)

            dashboard_path = root / "web" / "data" / "dashboard.json"
            dashboard = export_currency_dashboard(
                database_path,
                dashboard_path,
                scope="Cactuar",
                valuation_run_id=summary.valuation_run_id,
            )
            exported = json.loads(dashboard_path.read_text(encoding="utf-8"))
            self.assertEqual(dashboard.conversions, 1)
            self.assertEqual(exported["meta"]["scope"], "Cactuar")
            self.assertEqual(exported["meta"]["scopeLevel"], "WORLD")
            self.assertEqual(exported["conversions"][0]["rewardName"], "Fire Shard")

    def test_rejects_invalid_fee(self) -> None:
        with self.assertRaisesRegex(ValueError, "fee_rate"):
            build_currency_valuations("unused.sqlite3", scope="Aether", fee_rate=1)


if __name__ == "__main__":
    unittest.main()
