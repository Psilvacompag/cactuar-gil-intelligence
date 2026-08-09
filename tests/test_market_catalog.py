from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from gil_intelligence.storage import import_universalis_aggregates


def example_payload() -> dict[str, object]:
    return {
        "results": [
            {
                "itemId": 2,
                "nq": {
                    "minListing": {
                        "dc": {"price": 68, "worldId": 57},
                        "region": {"price": 45, "worldId": 81},
                    },
                    "medianListing": {
                        "dc": {"price": 70},
                        "region": {"price": 50},
                    },
                    "recentPurchase": {
                        "dc": {"price": 78, "timestamp": 1786308501000, "worldId": 63},
                        "region": {"price": 78, "timestamp": 1786308501000, "worldId": 63},
                    },
                    "averageSalePrice": {
                        "dc": {"price": 73.4},
                        "region": {"price": 58.1},
                    },
                    "dailySaleVelocity": {
                        "dc": {"quantity": 219383.2},
                        "region": {"quantity": 813229.8},
                    },
                },
                "hq": {
                    "minListing": {},
                    "medianListing": {},
                    "recentPurchase": {},
                    "averageSalePrice": {},
                    "dailySaleVelocity": {},
                },
                "worldUploadTimes": [
                    {"worldId": 57, "timestamp": 1786309130257},
                    {"worldId": 81, "timestamp": 1786306856241},
                ],
            }
        ],
        "failedItems": [999999],
    }


class MarketCatalogImportTests(unittest.TestCase):
    def test_imports_qualities_scopes_failures_and_freshness_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "catalog.sqlite3"
            first = import_universalis_aggregates(
                example_payload(),
                database_path,
                scope="Aether",
                collected_at="2026-08-09T21:06:59+00:00",
                requested_items=2,
                request_count=1,
                collection_elapsed_seconds=0.5,
            )
            second = import_universalis_aggregates(
                example_payload(),
                database_path,
                scope="Aether",
                collected_at="2026-08-09T21:06:59Z",
                requested_items=2,
                request_count=1,
                collection_elapsed_seconds=0.5,
            )

            self.assertEqual(first, second)
            self.assertEqual(first.aggregate_rows, 4)
            self.assertEqual(first.freshness_rows, 2)
            connection = sqlite3.connect(database_path)
            try:
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "market_source_snapshot",
                        "fact_market_aggregate_snapshot",
                        "fact_data_freshness",
                        "market_snapshot_failure",
                    )
                }
                nq_dc = connection.execute(
                    """
                    SELECT min_listing_price, median_listing_price, recent_purchase_price,
                           average_sale_price, daily_sale_velocity
                    FROM market_aggregate_with_freshness
                    WHERE quality = 'NQ' AND scope_level = 'DC'
                    """
                ).fetchone()
                telemetry = connection.execute(
                    "SELECT request_count, collection_elapsed_seconds FROM market_source_snapshot"
                ).fetchone()
                hq_dc = connection.execute(
                    """
                    SELECT min_listing_price, latest_upload_at
                    FROM market_aggregate_with_freshness
                    WHERE quality = 'HQ' AND scope_level = 'DC'
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(
                counts,
                {
                    "market_source_snapshot": 1,
                    "fact_market_aggregate_snapshot": 4,
                    "fact_data_freshness": 2,
                    "market_snapshot_failure": 1,
                },
            )
            self.assertEqual(nq_dc, (68.0, 70.0, 78.0, 73.4, 219383.2))
            self.assertEqual(hq_dc, (None, "2026-08-09T20:58:50.257000+00:00"))
            self.assertEqual(telemetry, (1, 0.5))

    def test_rejects_naive_collection_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "include a timezone"):
                import_universalis_aggregates(
                    example_payload(),
                    Path(directory) / "catalog.sqlite3",
                    scope="Aether",
                    collected_at="2026-08-09T21:06:59",
                )

    def test_rejects_duplicate_result_items(self) -> None:
        payload = example_payload()
        payload["results"] = [payload["results"][0], payload["results"][0]]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Duplicate result itemId"):
                import_universalis_aggregates(
                    payload,
                    Path(directory) / "catalog.sqlite3",
                    scope="Aether",
                    collected_at="2026-08-09T21:06:59Z",
                    requested_items=3,
                )


if __name__ == "__main__":
    unittest.main()
