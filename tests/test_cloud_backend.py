import json
import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gil_intelligence.cloud.config import CloudSettings
from gil_intelligence.cloud.dashboard import DashboardCache
from gil_intelligence.cloud.gcs import StoredObject
from gil_intelligence.cloud.quality import DataQualityError, evaluate_refresh_quality
from gil_intelligence.cloud.runner import _conversion_depth_candidates
from gil_intelligence.cloud.api import _accepts_gzip, _age_hours
from gil_intelligence.storage import MarketImportSummary
from gil_intelligence.storage.retention import prune_market_history


class FakeStore:
    def __init__(self) -> None:
        self.calls = 0

    def download(self, object_name: str) -> StoredObject:
        self.calls += 1
        return StoredObject(
            content=json.dumps({"schemaVersion": 1, "object": object_name}).encode(),
            generation=str(self.calls),
            updated_at="2026-08-09T12:00:00+00:00",
        )


class CloudSettingsTests(unittest.TestCase):
    def test_requires_bucket(self) -> None:
        with self.assertRaisesRegex(ValueError, "CACTUAR_BUCKET"):
            CloudSettings.from_environ({})

    def test_parses_runtime_configuration(self) -> None:
        settings = CloudSettings.from_environ(
            {
                "CACTUAR_BUCKET": "gs://example-data/",
                "CACTUAR_SCOPE": "Cactuar",
                "CACTUAR_RPS": "0.5",
                "CACTUAR_ALLOWED_ORIGINS": "https://example.test/,http://localhost:8000",
            }
        )

        self.assertEqual(settings.bucket, "example-data")
        self.assertEqual(settings.requests_per_second, 0.5)
        self.assertEqual(
            settings.allowed_origins,
            ("https://example.test", "http://localhost:8000"),
        )

    def test_health_age_rejects_invalid_or_naive_dates(self) -> None:
        self.assertIsNone(_age_hours("not-a-date"))
        self.assertIsNone(_age_hours("2026-08-09T12:00:00"))

    def test_gzip_content_negotiation_respects_quality(self) -> None:
        self.assertTrue(_accepts_gzip("br, gzip"))
        self.assertTrue(_accepts_gzip("*;q=0.5"))
        self.assertFalse(_accepts_gzip("gzip;q=0, br"))

    def test_conversion_depth_shortlist_covers_currencies_and_deduplicates_rewards(self) -> None:
        dashboard = {
            "conversions": [
                {"status": "FRESH", "rewardItemId": 100, "currencyItemId": 1, "netGilPerCurrency": 30, "dailySaleVelocity": None},
                {"status": "FRESH", "rewardItemId": 100, "currencyItemId": 2, "netGilPerCurrency": 20, "dailySaleVelocity": 50},
                {"status": "FRESH", "rewardItemId": 200, "currencyItemId": 2, "netGilPerCurrency": 10, "dailySaleVelocity": 25},
                {"status": "STALE", "rewardItemId": 300, "currencyItemId": 3, "netGilPerCurrency": 999, "dailySaleVelocity": 99},
            ]
        }

        candidates = _conversion_depth_candidates(dashboard, limit=3)

        self.assertEqual(candidates, [
            {"itemId": 100, "sourceWorldId": 79},
            {"itemId": 200, "sourceWorldId": 79},
        ])


class DashboardCacheTests(unittest.TestCase):
    def test_caches_dashboard_for_configured_ttl(self) -> None:
        now = [10.0]
        store = FakeStore()
        cache = DashboardCache(store, "public/dashboard.json", ttl_seconds=60, monotonic=lambda: now[0])

        first = cache.get()
        now[0] = 50.0
        second = cache.get()
        now[0] = 71.0
        third = cache.get()

        self.assertIs(first, second)
        self.assertEqual(store.calls, 2)
        self.assertEqual(third.generation, "2")
        self.assertEqual(first.etag, '"gcs-1"')
        self.assertEqual(gzip.decompress(first.compressed_content), first.content)

    def test_rejects_unknown_dashboard_schema(self) -> None:
        class InvalidStore:
            def download(self, object_name: str) -> StoredObject:
                del object_name
                return StoredObject(b'{"schemaVersion":2}', "1", None)

        with self.assertRaisesRegex(ValueError, "unsupported schema"):
            DashboardCache(InvalidStore(), "dashboard.json").get()


class MarketRetentionTests(unittest.TestCase):
    def test_keeps_latest_snapshots_for_requested_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "retention.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE market_source_snapshot (
                    market_snapshot_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    collected_at TEXT NOT NULL
                );
                CREATE TABLE child (
                    market_snapshot_id TEXT PRIMARY KEY,
                    FOREIGN KEY (market_snapshot_id)
                        REFERENCES market_source_snapshot(market_snapshot_id) ON DELETE CASCADE
                );
                """
            )
            for index in range(4):
                snapshot_id = f"cactuar-{index}"
                connection.execute(
                    "INSERT INTO market_source_snapshot VALUES (?, 'Cactuar', ?)",
                    (snapshot_id, f"2026-08-0{index + 1}T00:00:00+00:00"),
                )
                connection.execute("INSERT INTO child VALUES (?)", (snapshot_id,))
            connection.execute(
                "INSERT INTO market_source_snapshot VALUES ('aether-1', 'Aether', '2026-08-01T00:00:00+00:00')"
            )
            connection.commit()
            connection.close()

            summary = prune_market_history(database, scope="Cactuar", keep_snapshots=2)

            connection = sqlite3.connect(database)
            remaining = connection.execute(
                "SELECT market_snapshot_id FROM market_source_snapshot ORDER BY market_snapshot_id"
            ).fetchall()
            child_count = connection.execute("SELECT COUNT(*) FROM child").fetchone()[0]
            connection.close()
            self.assertEqual(summary.kept_snapshots, 2)
            self.assertEqual(summary.removed_snapshots, 2)
            self.assertEqual(remaining, [("aether-1",), ("cactuar-2",), ("cactuar-3",)])
            self.assertEqual(child_count, 2)


class RefreshQualityTests(unittest.TestCase):
    def test_accepts_complete_refresh_and_warns_on_identical_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "quality.sqlite3"
            dashboard = root / "dashboard.json"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE market_source_snapshot (
                    market_snapshot_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                "INSERT INTO market_source_snapshot VALUES (?, 'Cactuar', ?, 'same')",
                (
                    ("first", "2026-08-09T00:00:00+00:00"),
                    ("second", "2026-08-09T12:00:00+00:00"),
                ),
            )
            connection.commit()
            connection.close()
            dashboard.write_text(
                json.dumps({"summary": {"directConversions": 800, "fresh": 700}}),
                encoding="utf-8",
            )
            market = MarketImportSummary(
                database_path=database,
                snapshot_id="second",
                scope="Cactuar",
                collected_at="2026-08-09T12:00:00+00:00",
                requested_items=1000,
                result_items=995,
                failed_items=5,
                aggregate_rows=1,
                freshness_rows=1,
            )

            report = evaluate_refresh_quality(database, dashboard, market)

            self.assertAlmostEqual(report.coverage_ratio, 0.995)
            self.assertTrue(report.stagnant_payload)
            self.assertEqual(len(report.warnings), 1)

    def test_rejects_incomplete_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "quality.sqlite3"
            dashboard = root / "dashboard.json"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE market_source_snapshot (
                    market_snapshot_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO market_source_snapshot VALUES ('bad', 'Cactuar', '2026-08-09T12:00:00+00:00', 'bad')"
            )
            connection.commit()
            connection.close()
            dashboard.write_text(
                json.dumps({"summary": {"directConversions": 20, "fresh": 5}}),
                encoding="utf-8",
            )
            market = MarketImportSummary(
                database_path=database,
                snapshot_id="bad",
                scope="Cactuar",
                collected_at="2026-08-09T12:00:00+00:00",
                requested_items=1000,
                result_items=700,
                failed_items=300,
                aggregate_rows=1,
                freshness_rows=1,
            )

            with self.assertRaisesRegex(DataQualityError, "coverage"):
                evaluate_refresh_quality(database, dashboard, market)


if __name__ == "__main__":
    unittest.main()
