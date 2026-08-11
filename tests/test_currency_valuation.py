from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gil_intelligence.collectors import DetailedListingCollection
from gil_intelligence.publishing import (
    export_currency_dashboard,
    export_currency_history,
    export_market_items,
    export_opportunities,
)
from gil_intelligence.storage import (
    import_detailed_listings,
    import_static_snapshot,
    import_universalis_aggregates,
)
from gil_intelligence.valuation import build_currency_valuations, get_top_currency_conversions

from test_static_catalog import example_snapshot


class CurrencyValuationTests(unittest.TestCase):
    def test_dashboard_includes_marketable_multi_currency_exchange(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "catalog.sqlite3"
            static_payload = example_snapshot()
            static_payload["schemaVersion"] = 9
            static_payload["recipes"] = []
            static_payload["recipeIngredients"] = []
            static_payload["shopLocations"] = [{
                "shopId": 10,
                "npcId": 1008119,
                "npcName": "Auriana",
                "levelRowId": 4374264,
                "mapId": 25,
                "mapAssetId": "l1f1/01",
                "placeName": "Mor Dhona",
                "regionName": "Mor Dhona",
                "territoryId": 156,
                "worldX": 62.3635,
                "worldY": 31.288,
                "worldZ": -739.956,
                "mapX": 22.7,
                "mapY": 6.7,
                "markerLeftPercent": 53.045,
                "markerTopPercent": 13.869,
                "confidence": "DIRECT_ENPC_LEVEL",
            }]
            static_payload["assets"][0].update(
                {"itemId": 32180, "name": "Bozjan Gold Coin", "iconId": 26325}
            )
            static_payload["assets"][1].update(
                {
                    "itemId": 32835,
                    "name": "Modern Aesthetics - Early to Rise",
                    "marketableCandidate": True,
                }
            )
            static_payload["assets"].append(
                {
                    "itemId": 33796,
                    "name": "Bozjan Platinum Coin",
                    "iconId": 26329,
                    "marketableCandidate": False,
                }
            )
            static_payload["costs"][0].update({"itemId": 32180, "quantity": 5})
            static_payload["costs"].append(
                {
                    "shopId": 10,
                    "offerIndex": 2,
                    "costIndex": 1,
                    "rawItemId": 33796,
                    "itemId": 33796,
                    "quantity": 30,
                    "costType": 0,
                }
            )
            static_payload["rewards"][0].update(
                {"itemId": 32835, "quantity": 1, "isHq": False}
            )
            snapshot_path = root / "static.json"
            snapshot_path.write_text(json.dumps(static_payload), encoding="utf-8")
            import_static_snapshot(snapshot_path, database_path)
            now = datetime.now(timezone.utc)
            upload_millis = int(now.timestamp() * 1000)
            import_universalis_aggregates(
                {
                    "results": [{
                        "itemId": 32835,
                        "nq": {
                            "minListing": {"world": {"price": 1_000_000, "worldId": 79}},
                            "medianListing": {"world": {"price": 1_100_000}},
                            "recentPurchase": {},
                            "averageSalePrice": {"world": {"price": 950_000}},
                            "dailySaleVelocity": {"world": {"quantity": 1.5}},
                        },
                        "hq": {},
                        "worldUploadTimes": [{"worldId": 79, "timestamp": upload_millis}],
                    }],
                    "failedItems": [],
                },
                database_path,
                scope="Cactuar",
                collected_at=now.isoformat(),
                requested_items=1,
            )
            valuation = build_currency_valuations(
                database_path,
                scope="Cactuar",
                as_of=now,
            )

            dashboard_path = root / "dashboard.json"
            export_currency_dashboard(
                database_path,
                dashboard_path,
                scope="Cactuar",
                valuation_run_id=valuation.valuation_run_id,
            )
            exported = json.loads(dashboard_path.read_text(encoding="utf-8"))
            rows = exported["conversions"]

            self.assertEqual(valuation.eligible_offers, 1)
            self.assertEqual(exported["summary"]["directConversions"], 1)
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row["currencyName"] for row in rows},
                {"Bozjan Gold Coin", "Bozjan Platinum Coin"},
            )
            self.assertTrue(all(row["isMultiCost"] for row in rows))
            self.assertTrue(all(row["status"] == "FRESH" for row in rows))
            self.assertTrue(all(row["netGilPerCurrency"] is None for row in rows))
            self.assertTrue(all(row["netGilPerExchange"] == 950_000 for row in rows))
            self.assertTrue(all(len(row["costComponents"]) == 2 for row in rows))
            self.assertTrue(all(row["locations"][0]["npcName"] == "Auriana" for row in rows))
            self.assertTrue(all(row["locations"][0]["mapAssetId"] == "l1f1/01" for row in rows))

    def test_dashboard_audits_but_does_not_publish_non_tradeable_exchanges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "catalog.sqlite3"
            static_payload = example_snapshot()
            static_payload["assets"][0].update(
                {"itemId": 32180, "name": "Bozjan Gold Coin", "iconId": 26325}
            )
            static_payload["assets"][1].update(
                {
                    "itemId": 32723,
                    "name": "Law's Order Helm of Fending",
                    "marketableCandidate": False,
                }
            )
            static_payload["costs"][0].update({"itemId": 32180, "quantity": 2})
            static_payload["rewards"][0].update(
                {"itemId": 32723, "quantity": 1, "isHq": False}
            )
            snapshot_path = root / "static.json"
            snapshot_path.write_text(json.dumps(static_payload), encoding="utf-8")
            import_static_snapshot(snapshot_path, database_path)
            import_universalis_aggregates(
                {"results": [], "failedItems": []},
                database_path,
                scope="Cactuar",
                collected_at=datetime.now(timezone.utc).isoformat(),
                requested_items=0,
            )
            valuation = build_currency_valuations(
                database_path,
                scope="Cactuar",
                as_of=datetime.now(timezone.utc),
            )

            dashboard_path = root / "dashboard.json"
            dashboard = export_currency_dashboard(
                database_path,
                dashboard_path,
                scope="Cactuar",
                valuation_run_id=valuation.valuation_run_id,
            )
            exported = json.loads(dashboard_path.read_text(encoding="utf-8"))

            self.assertEqual(dashboard.conversions, 0)
            self.assertEqual(exported["summary"]["directConversions"], 0)
            self.assertEqual(exported["summary"]["catalogConversions"], 0)
            self.assertEqual(exported["summary"]["notTradeable"], 1)
            self.assertEqual(exported["conversions"], [])
            self.assertEqual(exported["currencies"], [])

    def test_market_export_includes_current_materia_for_expansion_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "catalog.sqlite3"
            static_payload = example_snapshot()
            static_payload["schemaVersion"] = 3
            static_payload["assets"].append(
                {
                    "itemId": 41766,
                    "name": "Craftsman's Cunning Materia XI",
                    "marketableCandidate": True,
                    "searchCategoryId": 63,
                    "searchCategoryName": "Materia",
                    "uiCategoryId": 60,
                    "uiCategoryName": "Materia",
                    "craftable": False,
                    "gatherable": False,
                }
            )
            snapshot_path = root / "static.json"
            snapshot_path.write_text(json.dumps(static_payload), encoding="utf-8")
            import_static_snapshot(snapshot_path, database_path)
            upload_millis = int(datetime.now(timezone.utc).timestamp() * 1000)
            import_universalis_aggregates(
                {
                    "results": [
                        {
                            "itemId": 41766,
                            "nq": {
                                "minListing": {"world": {"price": 5000, "worldId": 79}},
                                "medianListing": {"world": {"price": 5200}},
                                "recentPurchase": {},
                                "averageSalePrice": {"world": {"price": 5100}},
                                "dailySaleVelocity": {"world": {"quantity": 200}},
                            },
                            "hq": {},
                            "worldUploadTimes": [
                                {"worldId": 79, "timestamp": upload_millis}
                            ],
                        }
                    ],
                    "failedItems": [],
                },
                database_path,
                scope="Cactuar",
                collected_at=datetime.now(timezone.utc).isoformat(),
                requested_items=1,
                request_count=1,
                collection_elapsed_seconds=0.1,
            )
            market_path = root / "market-items.json"
            summary = export_market_items(
                database_path,
                market_path,
                scope="Cactuar",
            )
            exported = json.loads(market_path.read_text(encoding="utf-8"))

            self.assertEqual(summary.rows, 1)
            self.assertEqual(exported["items"][0]["itemId"], 41766)
            self.assertEqual(exported["items"][0]["searchCategoryName"], "Materia")
            self.assertFalse(exported["items"][0]["craftable"])
            self.assertFalse(exported["items"][0]["gatherable"])
            self.assertEqual(exported["items"][0]["trend"]["historyPoints"], 1)

    def test_values_simple_currency_offer_with_fee_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "catalog.sqlite3"
            static_payload = example_snapshot()
            static_payload["schemaVersion"] = 3
            static_payload["assets"][1]["itemId"] = 2
            static_payload["assets"][1]["name"] = "Fire Shard"
            static_payload["assets"][1].update(
                {
                    "craftable": True,
                    "craftTypeName": "Goldsmith",
                    "gatherable": True,
                    "gatheringType": "MINER_BOTANIST",
                }
            )
            static_payload["rewards"][0].update(
                {"itemId": 2, "quantity": 2, "isHq": False}
            )
            snapshot_path = root / "static.json"
            snapshot_path.write_text(json.dumps(static_payload), encoding="utf-8")
            import_static_snapshot(snapshot_path, database_path)
            market_import = import_universalis_aggregates(
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
                                    # An outlier sale must not inflate the actionable
                                    # conversion value above the current listing.
                                    "world": {"price": 2194.645},
                                    "dc": {"price": 1021.095},
                                },
                                "dailySaleVelocity": {
                                    "world": {"quantity": 3},
                                    "dc": {"quantity": 12},
                                },
                            },
                            "hq": {},
                            "worldUploadTimes": [
                                {"worldId": 57, "timestamp": 1786309130257},
                                {"worldId": 79, "timestamp": 1786309130257},
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
            self.assertEqual(summary.price_basis, "MIN_LISTING")
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
            self.assertEqual(exported["meta"]["priceBasis"], "MIN_LISTING")
            self.assertEqual(exported["conversions"][0]["rewardName"], "Fire Shard")
            self.assertIsNone(exported["conversions"][0]["listingDepth"])

            import_detailed_listings(
                DetailedListingCollection(
                    requested_pairs=((79, 2),),
                    batch_count=1,
                    items=(
                        {
                            "itemId": 2,
                            "worldId": 79,
                            "lastUploadTime": 1786309130257,
                            "listings": [
                                {
                                    "rank": 0,
                                    "listingId": "floor",
                                    "pricePerUnit": 80,
                                    "quantity": 2,
                                    "hq": False,
                                    "lastReviewTime": 1786309130,
                                },
                                {
                                    "rank": 1,
                                    "listingId": "next",
                                    "pricePerUnit": 88,
                                    "quantity": 4,
                                    "hq": False,
                                    "lastReviewTime": 1786309130,
                                },
                                {
                                    "rank": 2,
                                    "listingId": "high",
                                    "pricePerUnit": 120,
                                    "quantity": 20,
                                    "hq": False,
                                    "lastReviewTime": 1786309130,
                                },
                            ],
                        },
                    ),
                ),
                database_path,
                market_snapshot_id=market_import.snapshot_id,
                collected_at="2026-08-09T21:07:00+00:00",
                request_count=1,
            )
            export_currency_dashboard(
                database_path,
                dashboard_path,
                scope="Cactuar",
                valuation_run_id=summary.valuation_run_id,
            )
            depth = json.loads(dashboard_path.read_text(encoding="utf-8"))["conversions"][0]["listingDepth"]
            self.assertTrue(depth["verified"])
            self.assertEqual(depth["nearFloorUnits"], 6)
            self.assertEqual(depth["pressure"], "HIGH")
            self.assertAlmostEqual(depth["nearFloorSupplyDays"], 2.0)
            self.assertEqual(depth["weightedUnitCount"], 20)

            history_path = root / "web" / "data" / "history.json"
            history = export_currency_history(database_path, history_path, scope="Cactuar")
            exported_history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(history.series, 1)
            self.assertEqual(history.points, 1)
            self.assertEqual(exported_history["kind"], "currency-history")
            self.assertEqual(exported_history["series"][0]["key"], "28:20:2:2:0")
            self.assertAlmostEqual(
                exported_history["series"][0]["points"][0]["netGilPerCurrency"],
                7.6,
            )

            market_path = root / "web" / "data" / "market-items.json"
            market = export_market_items(
                database_path,
                market_path,
                scope="Cactuar",
                freshness_hours=24,
            )
            exported_market = json.loads(market_path.read_text(encoding="utf-8"))
            self.assertEqual(market.rows, 1)
            self.assertEqual(market.gathering_items, 1)
            self.assertEqual(market.crafting_items, 1)
            self.assertEqual(exported_market["kind"], "market-items")
            self.assertEqual(exported_market["items"][0]["name"], "Fire Shard")
            self.assertTrue(exported_market["items"][0]["gatherable"])
            market_depth = exported_market["items"][0]["listingDepth"]
            self.assertTrue(market_depth["verified"])
            self.assertEqual(market_depth["nearFloorUnits"], 6)
            self.assertEqual(market_depth["weightedUnitCount"], 20)

    def test_exports_conservative_cross_world_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "catalog.sqlite3"
            static_payload = example_snapshot()
            static_payload["schemaVersion"] = 3
            static_payload["assets"][1].update(
                {
                    "name": "Fire Shard",
                    "craftable": True,
                    "craftTypeName": "Goldsmith",
                    "gatherable": True,
                    "gatheringType": "MINER_BOTANIST",
                }
            )
            snapshot_path = root / "static.json"
            snapshot_path.write_text(json.dumps(static_payload), encoding="utf-8")
            import_static_snapshot(snapshot_path, database_path)
            now = datetime.now(timezone.utc)
            upload_millis = int(now.timestamp() * 1000)
            market_import = import_universalis_aggregates(
                {
                    "results": [
                        {
                            "itemId": 100,
                            "nq": {
                                "minListing": {
                                    "world": {"price": 10000, "worldId": 79},
                                    "dc": {"price": 3000, "worldId": 57},
                                    "region": {"price": 3000, "worldId": 35},
                                },
                                "medianListing": {
                                    "world": {"price": 11000},
                                    "dc": {"price": 3500},
                                    "region": {"price": 3500},
                                },
                                "recentPurchase": {},
                                "averageSalePrice": {
                                    "world": {"price": 9000},
                                    "dc": {"price": 3300},
                                    "region": {"price": 3300},
                                },
                                "dailySaleVelocity": {
                                    "world": {"quantity": 20},
                                    "dc": {"quantity": 100},
                                    "region": {"quantity": 300},
                                },
                            },
                            "hq": {},
                            "worldUploadTimes": [
                                {"worldId": 57, "timestamp": upload_millis},
                                {"worldId": 35, "timestamp": upload_millis},
                                {"worldId": 79, "timestamp": upload_millis},
                            ],
                        }
                    ],
                    "failedItems": [],
                },
                database_path,
                scope="Cactuar",
                collected_at=now.isoformat(),
                requested_items=1,
            )

            import_detailed_listings(
                DetailedListingCollection(
                    requested_pairs=((35, 100),),
                    batch_count=1,
                    items=(
                        {
                            "itemId": 100,
                            "worldId": 35,
                            "lastUploadTime": upload_millis,
                            "listings": [
                                {
                                    "rank": 0,
                                    "listingId": "listing-1",
                                    "pricePerUnit": 3000,
                                    "quantity": 10,
                                    "hq": False,
                                    "lastReviewTime": int(now.timestamp()),
                                }
                            ],
                        },
                    ),
                ),
                database_path,
                market_snapshot_id=market_import.snapshot_id,
                collected_at=now.isoformat(),
                request_count=1,
            )

            output_path = root / "opportunities.json"
            summary = export_opportunities(database_path, output_path, scope="Cactuar")
            exported = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(summary.opportunities, 1)
            opportunity = exported["opportunities"][0]
            self.assertEqual(opportunity["sourceWorldName"], "Famfrit")
            self.assertEqual(opportunity["sourceDataCenterName"], "Primal")
            self.assertEqual(exported["meta"]["sourceScope"], "North-America")
            self.assertEqual(opportunity["recommendedQuantity"], 5)
            self.assertAlmostEqual(opportunity["unitProfit"], 3840)
            self.assertEqual(opportunity["confidenceBand"], "HIGH")
            self.assertTrue(opportunity["stockVerified"])
            self.assertEqual(opportunity["availableUnits"], 10)

    def test_rejects_invalid_fee(self) -> None:
        with self.assertRaisesRegex(ValueError, "fee_rate"):
            build_currency_valuations("unused.sqlite3", scope="Aether", fee_rate=1)


if __name__ == "__main__":
    unittest.main()
