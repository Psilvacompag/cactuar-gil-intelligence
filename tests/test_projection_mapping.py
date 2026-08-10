from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectionMappingTests(unittest.TestCase):
    def test_historical_examples_are_not_reused_as_candidates(self) -> None:
        mapping = json.loads(
            (ROOT / "apps/web/data/launch-signals.json").read_text(encoding="utf-8")
        )
        evidence = json.loads(
            (ROOT / "docs/data/expansion_launch_evidence.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(mapping["schemaVersion"], 2)
        candidate_ids: list[int] = []
        for pattern in mapping["patterns"]:
            self.assertNotIn("categoryNames", pattern)
            self.assertNotIn("itemIds", pattern)
            self.assertTrue(pattern["currentItemIds"])
            self.assertTrue(pattern["historicalExamples"])
            self.assertTrue(pattern["currentRationale"])
            candidate_ids.extend(pattern["currentItemIds"])
        self.assertEqual(len(candidate_ids), len(set(candidate_ids)))

        historical_ids: set[int] = set()
        for entry in evidence["entries"]:
            if entry.get("itemId") is not None:
                historical_ids.add(entry["itemId"])
            historical_ids.update(entry.get("itemIds", []))
        overlap = set(candidate_ids) & historical_ids

        # Persistent crystals and current Materia XI are deliberate exceptions:
        # they remain stockable and can fill a new 8.0 role. Expansion-specific
        # finished goods and materials must never leak into the candidate list.
        reusable_bridge_ids = set(range(8, 20)) | set(range(41757, 41770))
        self.assertLessEqual(overlap, reusable_bridge_ids)


if __name__ == "__main__":
    unittest.main()
