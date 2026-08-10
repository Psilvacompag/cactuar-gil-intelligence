from __future__ import annotations

import unittest

from gil_intelligence.collectors import collect_aggregated_market, collect_detailed_listings
from gil_intelligence.probes.models import JsonResponse


class StubClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def get_json(self, path: str, query: dict[str, object] | None = None) -> JsonResponse:
        del query
        self.paths.append(path)
        ids = [int(value) for value in path.rsplit("/", 1)[-1].split(",")]
        return JsonResponse(
            url=f"https://stub.test{path}",
            status=200,
            headers={},
            data={
                "results": [
                    {"itemId": item_id, "nq": {}, "hq": {}, "worldUploadTimes": []}
                    for item_id in ids
                ],
                "failedItems": [],
            },
            elapsed_ms=1,
        )


class UniversalisCollectorTests(unittest.TestCase):
    def test_batches_at_one_hundred_and_deduplicates_ids(self) -> None:
        client = StubClient()
        progress: list[tuple[int, int]] = []
        collection = collect_aggregated_market(
            client,
            scope="North America/Aether",
            item_ids=[*range(1, 206), 1],
            progress=lambda completed, total: progress.append((completed, total)),
        )

        self.assertEqual(collection.batch_count, 3)
        self.assertEqual(len(collection.requested_item_ids), 205)
        self.assertEqual(len(collection.payload["results"]), 205)
        self.assertTrue(client.paths[0].startswith("/api/v2/aggregated/North%20America%2FAether/"))
        self.assertEqual(len(client.paths[0].rsplit("/", 1)[-1].split(",")), 100)
        self.assertEqual(len(client.paths[-1].rsplit("/", 1)[-1].split(",")), 5)
        self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])

    def test_rejects_oversized_batch(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            collect_aggregated_market(StubClient(), scope="Aether", item_ids=[1], batch_size=101)

    def test_groups_detailed_shortlist_by_world(self) -> None:
        class DetailedStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object] | None]] = []

            def get_json(
                self,
                path: str,
                query: dict[str, object] | None = None,
            ) -> JsonResponse:
                self.calls.append((path, query))
                world_id = int(path.split("/")[3])
                item_ids = [int(value) for value in path.rsplit("/", 1)[-1].split(",")]
                items = {
                    str(item_id): {
                        "itemID": item_id,
                        "lastUploadTime": 1786309130257,
                        "listings": [
                            {
                                "listingID": f"{world_id}-{item_id}",
                                "pricePerUnit": 1000 + item_id,
                                "quantity": 3,
                                "hq": False,
                                "lastReviewTime": 1786309130,
                            }
                        ],
                    }
                    for item_id in item_ids
                }
                return JsonResponse(
                    url=f"https://stub.test{path}",
                    status=200,
                    headers={},
                    data={"items": items, "unresolvedItems": []},
                    elapsed_ms=1,
                )

        client = DetailedStub()
        collection = collect_detailed_listings(
            client,
            candidates=[
                {"itemId": 10, "sourceWorldId": 57},
                {"itemId": 11, "sourceWorldId": 57},
                {"itemId": 12, "sourceWorldId": 99},
                {"itemId": 10, "sourceWorldId": 57},
            ],
        )

        self.assertEqual(collection.batch_count, 2)
        self.assertEqual(len(collection.requested_pairs), 3)
        self.assertEqual(len(collection.items), 3)
        self.assertEqual(client.calls[0][1], {"listings": 20, "entries": 0})
        self.assertIn("/57/10,11", client.calls[0][0])


if __name__ == "__main__":
    unittest.main()
