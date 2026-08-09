import unittest

from gil_intelligence.probes.budget import estimate_market_request_budget


class MarketRequestBudgetTests(unittest.TestCase):
    def test_budget_uses_hundred_item_batches(self) -> None:
        budget = estimate_market_request_budget(30_000)

        self.assertEqual(budget["full_snapshot_requests"], 300)
        self.assertEqual(budget["full_daily_requests"], 1_200)
        self.assertEqual(budget["candidate_daily_requests"], 480)
        self.assertEqual(budget["total_daily_requests"], 1_680)
        self.assertEqual(budget["full_snapshot_minimum_seconds"], 150.0)

    def test_partial_batch_rounds_up(self) -> None:
        budget = estimate_market_request_budget(101, candidate_items=0)
        self.assertEqual(budget["full_snapshot_requests"], 2)

    def test_invalid_budget_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            estimate_market_request_budget(-1)


if __name__ == "__main__":
    unittest.main()

