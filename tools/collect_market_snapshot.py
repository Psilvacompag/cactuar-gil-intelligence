from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from gil_intelligence.collectors import collect_aggregated_market  # noqa: E402
from gil_intelligence.probes.http import JsonHttpClient  # noqa: E402
from gil_intelligence.storage import import_universalis_aggregates  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect and persist a Universalis aggregate market snapshot."
    )
    parser.add_argument("--scope", default="Aether", help="World or Data Center name.")
    parser.add_argument(
        "--database",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "gil_intelligence.sqlite3",
        help="Target SQLite database.",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--all-marketable",
        action="store_true",
        help="Collect every ID in Universalis' marketable catalog.",
    )
    selection.add_argument(
        "--item-ids",
        help="Comma-separated item IDs, useful for a small validation run.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--rps",
        type=float,
        default=1.0,
        help="Maximum request starts per second (default: 1, well below the public limit).",
    )
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def _parse_item_ids(value: str) -> list[int]:
    try:
        item_ids = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError("--item-ids must be a comma-separated list of integers") from exc
    if not item_ids or any(item_id <= 0 for item_id in item_ids):
        raise ValueError("--item-ids must contain positive integers")
    return item_ids


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    client = JsonHttpClient(
        "https://universalis.app",
        timeout_seconds=args.timeout,
        requests_per_second=args.rps,
        max_retries=args.retries,
        user_agent="ffxiv-gil-intelligence/0.0.1",
    )
    if args.all_marketable:
        response = client.get_json("/api/v2/marketable")
        if not isinstance(response.data, list) or not all(
            isinstance(item_id, int) and not isinstance(item_id, bool) and item_id > 0
            for item_id in response.data
        ):
            raise ValueError("Universalis marketable response was not a positive integer list")
        item_ids = response.data
    else:
        item_ids = _parse_item_ids(args.item_ids)

    collected_at = datetime.now(timezone.utc).isoformat()

    def report_progress(completed: int, total: int) -> None:
        if completed == 1 or completed == total or completed % 10 == 0:
            print(f"Collected batch {completed}/{total}", file=sys.stderr, flush=True)

    collection = collect_aggregated_market(
        client,
        scope=args.scope,
        item_ids=item_ids,
        progress=report_progress,
    )
    collection_elapsed_seconds = round(time.monotonic() - started, 1)
    summary = import_universalis_aggregates(
        collection.payload,
        args.database,
        scope=collection.scope,
        collected_at=collected_at,
        requested_items=len(collection.requested_item_ids),
        request_count=client.request_attempt_count,
        collection_elapsed_seconds=collection_elapsed_seconds,
    )
    output = asdict(summary)
    output["database_path"] = str(summary.database_path)
    output["batch_count"] = collection.batch_count
    output["request_count"] = client.request_attempt_count
    output["successful_request_count"] = client.successful_request_count
    output["collection_elapsed_seconds"] = collection_elapsed_seconds
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
