from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from gil_intelligence.publishing import export_currency_dashboard  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export static dashboard JSON.")
    parser.add_argument("--scope", default="Cactuar")
    parser.add_argument(
        "--database",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "gil_intelligence.sqlite3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "apps" / "web" / "data" / "dashboard.json",
    )
    parser.add_argument("--valuation-run-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = export_currency_dashboard(
        args.database,
        args.output,
        scope=args.scope,
        valuation_run_id=args.valuation_run_id,
    )
    output = asdict(summary)
    output["output_path"] = str(summary.output_path)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
