from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from gil_intelligence.collectors import collect_aggregated_market  # noqa: E402
from gil_intelligence.probes.http import JsonHttpClient  # noqa: E402
from gil_intelligence.publishing import export_currency_dashboard  # noqa: E402
from gil_intelligence.storage import import_universalis_aggregates  # noqa: E402
from gil_intelligence.valuation import (  # noqa: E402
    DEFAULT_CURRENCY_PRICE_BASIS,
    build_currency_valuations,
    get_top_currency_conversions,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh the full market snapshot and rebuild currency valuations."
    )
    parser.add_argument("--scope", default="Aether")
    parser.add_argument(
        "--database",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "gil_intelligence.sqlite3",
    )
    parser.add_argument("--rps", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--fee-rate", type=float, default=0.05)
    parser.add_argument("--freshness-hours", type=float, default=24.0)
    parser.add_argument("--min-daily-velocity", type=float, default=0.1)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--dashboard-output",
        type=Path,
        default=REPOSITORY_ROOT / "apps" / "web" / "data" / "dashboard.json",
    )
    parser.add_argument("--no-export", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    lock_path = args.database.with_suffix(args.database.suffix + ".refresh.lock")
    with _exclusive_lock(lock_path):
        started = time.monotonic()
        client = JsonHttpClient(
            "https://universalis.app",
            timeout_seconds=args.timeout,
            requests_per_second=args.rps,
            max_retries=args.retries,
            user_agent="ffxiv-gil-intelligence/0.0.1",
        )
        marketable = client.get_json("/api/v2/marketable")
        if not isinstance(marketable.data, list) or not all(
            isinstance(item_id, int) and not isinstance(item_id, bool) and item_id > 0
            for item_id in marketable.data
        ):
            raise ValueError("Universalis marketable response was not a positive integer list")

        def report_progress(completed: int, total: int) -> None:
            if completed == 1 or completed == total or completed % 10 == 0:
                print(f"Collected batch {completed}/{total}", file=sys.stderr, flush=True)

        collected_at = datetime.now(timezone.utc).isoformat()
        collection = collect_aggregated_market(
            client,
            scope=args.scope,
            item_ids=marketable.data,
            progress=report_progress,
        )
        elapsed_seconds = round(time.monotonic() - started, 1)
        market_summary = import_universalis_aggregates(
            collection.payload,
            args.database,
            scope=args.scope,
            collected_at=collected_at,
            requested_items=len(collection.requested_item_ids),
            request_count=client.request_attempt_count,
            collection_elapsed_seconds=elapsed_seconds,
        )
        valuation_summary = build_currency_valuations(
            args.database,
            scope=args.scope,
            price_basis=DEFAULT_CURRENCY_PRICE_BASIS,
            fee_rate=args.fee_rate,
            freshness_hours=args.freshness_hours,
            market_snapshot_id=market_summary.snapshot_id,
        )
        dashboard_summary = (
            None
            if args.no_export
            else export_currency_dashboard(
                args.database,
                args.dashboard_output,
                scope=args.scope,
                valuation_run_id=valuation_summary.valuation_run_id,
            )
        )
        output = {
            "market": {
                **asdict(market_summary),
                "database_path": str(market_summary.database_path),
                "batch_count": collection.batch_count,
                "request_count": client.request_attempt_count,
                "successful_request_count": client.successful_request_count,
                "elapsed_seconds": elapsed_seconds,
            },
            "valuation": {
                **asdict(valuation_summary),
                "database_path": str(valuation_summary.database_path),
            },
            "top_conversions": get_top_currency_conversions(
                args.database,
                valuation_summary.valuation_run_id,
                limit=args.limit,
                fresh_only=True,
                minimum_daily_velocity=args.min_daily_velocity,
            ),
        }
        if dashboard_summary is not None:
            output["dashboard"] = {
                **asdict(dashboard_summary),
                "output_path": str(dashboard_summary.output_path),
            }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        _lock_byte(stream)
        try:
            yield
        finally:
            stream.seek(0)
            _unlock_byte(stream)


def _lock_byte(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another market refresh is already running") from exc
    else:
        import fcntl

        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another market refresh is already running") from exc


def _unlock_byte(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main())
