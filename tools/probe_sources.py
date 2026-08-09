from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from gil_intelligence.probes.budget import estimate_market_request_budget  # noqa: E402
from gil_intelligence.probes.runner import (  # noqa: E402
    SHOP_DISCOVERY_TOKENS,
    SHOP_SHEET_CANDIDATES,
    STRUCTURAL_SHEETS,
    build_feasibility_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe XIVAPI and Universalis contracts safely.")
    parser.add_argument("--live", action="store_true", help="Actually call the public APIs.")
    parser.add_argument("--scope", default="Aether", help="World or Data Center for Universalis.")
    parser.add_argument("--timeout", type=float, default=8.0, help="Timeout per request in seconds.")
    parser.add_argument("--rps", type=float, default=2.0, help="Maximum requests per second per source.")
    parser.add_argument("--retries", type=int, default=1, help="Retry count for transient errors/429s.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.live:
        planned = {
            "mode": "DRY_RUN",
            "scope": args.scope,
            "shop_sheet_candidates": list(SHOP_SHEET_CANDIDATES),
            "shop_discovery_tokens": list(SHOP_DISCOVERY_TOKENS),
            "structural_sheets": list(STRUCTURAL_SHEETS),
            "assumed_request_budget": estimate_market_request_budget(
                30_000,
                safe_requests_per_second=args.rps,
            ),
            "next": "Pass --live to call XIVAPI and Universalis.",
        }
        print(json.dumps(planned, indent=2, ensure_ascii=False))
        return 0

    report = build_feasibility_report(
        scope=args.scope,
        timeout_seconds=args.timeout,
        requests_per_second=args.rps,
        max_retries=args.retries,
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if all(source.status in {"PASS", "WARN"} for source in report.sources) else 2


if __name__ == "__main__":
    raise SystemExit(main())
