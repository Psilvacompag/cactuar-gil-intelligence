from __future__ import annotations

import unittest

from gil_intelligence.publishing.signal_candidates import signal_depth_candidates


class SignalCandidateTests(unittest.TestCase):
    def test_reserves_projection_and_ranks_snipe_candidates(self) -> None:
        market = {
            "items": [
                {
                    "itemId": 41766,
                    "quality": "NQ",
                    "status": "FRESH",
                    "minListingPrice": 5000,
                    "dailySaleVelocity": 20,
                },
                {
                    "itemId": 100,
                    "quality": "NQ",
                    "status": "FRESH",
                    "minListingPrice": 100,
                    "dailySaleVelocity": 30,
                },
                {
                    "itemId": 101,
                    "quality": "NQ",
                    "status": "FRESH",
                    "minListingPrice": 950,
                    "dailySaleVelocity": 30,
                },
            ]
        }
        history = {
            "series": [
                {
                    "key": "100:NQ",
                    "trend": {"priceVolatility": 0.1},
                    "points": [
                        {"minListingPrice": 1000, "averageSalePrice": 1000},
                        {"minListingPrice": 1000, "averageSalePrice": 1000},
                        {"minListingPrice": 100, "averageSalePrice": 1000},
                    ],
                },
                {
                    "key": "101:NQ",
                    "trend": {"priceVolatility": 0.1},
                    "points": [
                        {"minListingPrice": 1000, "averageSalePrice": 1000},
                        {"minListingPrice": 1000, "averageSalePrice": 1000},
                        {"minListingPrice": 950, "averageSalePrice": 1000},
                    ],
                },
            ]
        }

        candidates = signal_depth_candidates(market, history, snipe_limit=1)

        self.assertEqual(
            candidates,
            [
                {"itemId": 41766, "sourceWorldId": 79},
                {"itemId": 100, "sourceWorldId": 79},
            ],
        )


if __name__ == "__main__":
    unittest.main()
