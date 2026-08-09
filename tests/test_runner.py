import unittest

from gil_intelligence.probes.models import JsonResponse, ProbeStatus
from gil_intelligence.probes.runner import probe_universalis, probe_xivapi


class StubClient:
    base_url = "https://stub.test"

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses

    def get_json(self, path: str, query: dict[str, object] | None = None) -> JsonResponse:
        del query
        if path not in self.responses:
            raise AssertionError(f"Unexpected path: {path}")
        return JsonResponse(
            url=f"{self.base_url}{path}",
            status=200,
            headers={},
            data=self.responses[path],
            elapsed_ms=1,
        )


class XivapiProbeTests(unittest.TestCase):
    def test_discovers_shop_sheets_and_samples_shapes(self) -> None:
        client = StubClient(
            {
                "/api/version": {"versions": [{"key": "abc", "names": ["latest", "7.5"]}]},
                "/api/sheet": {
                    "sheets": [
                        {"name": "Item"},
                        {"name": "ENpcBase"},
                        {"name": "ENpcResident"},
                        {"name": "Level"},
                        {"name": "SpecialShop"},
                        {"name": "GilShop"},
                        {"name": "ExperimentalExchange"},
                    ]
                },
                "/api/sheet/SpecialShop": {
                    "version": "abc",
                    "schema": "schema@abc",
                    "rows": [{"row_id": 1, "fields": {"Name": "Example", "Item": []}}],
                },
                "/api/sheet/GilShop": {
                    "version": "abc",
                    "schema": "schema@abc",
                    "rows": [{"row_id": 1, "fields": {"Name": "Example"}}],
                },
            }
        )

        result = probe_xivapi(client)

        self.assertEqual(result.status, ProbeStatus.WARN)
        self.assertEqual(result.findings["present_shop_sheets"], ["SpecialShop", "GilShop"])
        self.assertIn("GCScripShopItem", result.findings["missing_shop_sheets"])
        self.assertEqual(result.findings["unclassified_shop_sheets"], ["ExperimentalExchange"])
        self.assertEqual(result.findings["missing_structural_sheets"], [])
        self.assertEqual(
            result.findings["sampled_shop_shapes"]["SpecialShop"]["top_level_fields"],
            ["Item", "Name"],
        )


class UniversalisProbeTests(unittest.TestCase):
    def test_counts_marketable_items_and_checks_aggregates(self) -> None:
        client = StubClient(
            {
                "/api/v2/data-centers": [{"name": "Aether", "worlds": [1]}],
                "/api/v2/marketable": [10, 20, 30, 40],
                "/api/v2/aggregated/Aether/10,20,30": {
                    "results": [{"itemId": 10}, {"itemId": 20}, {"itemId": 30}],
                    "failedItems": [],
                },
            }
        )

        result, marketable_count = probe_universalis(client, scope="Aether")

        self.assertEqual(result.status, ProbeStatus.PASS)
        self.assertEqual(marketable_count, 4)
        self.assertTrue(result.findings["scope_found"])


if __name__ == "__main__":
    unittest.main()
