from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from gil_intelligence.valuation import (  # noqa: E402
    DEFAULT_CURRENCY_PRICE_BASIS,
    build_currency_valuations,
    get_top_currency_conversions,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cross the static shop catalog with a persisted market snapshot."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "gil_intelligence.sqlite3",
    )
    parser.add_argument("--scope", default="Aether")
    parser.add_argument(
        "--price-basis",
        choices=("MIN_LISTING", "MEDIAN_LISTING", "RECENT_AVG_SALE"),
        default=DEFAULT_CURRENCY_PRICE_BASIS,
    )
    parser.add_argument("--fee-rate", type=float, default=0.05)
    parser.add_argument("--freshness-hours", type=float, default=24.0)
    parser.add_argument("--currency", help="Optional currency-name filter for the ranking.")
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--min-daily-velocity", type=float, default=0.1)
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_currency_valuations(
        args.database,
        scope=args.scope,
        price_basis=args.price_basis,
        fee_rate=args.fee_rate,
        freshness_hours=args.freshness_hours,
    )
    output = asdict(summary)
    output["database_path"] = str(summary.database_path)
    output["top_conversions"] = get_top_currency_conversions(
        args.database,
        summary.valuation_run_id,
        limit=args.limit,
        currency_query=args.currency,
        fresh_only=not args.include_stale,
        minimum_daily_velocity=args.min_daily_velocity,
    )
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
