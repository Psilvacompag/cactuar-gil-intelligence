from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from gil_intelligence.storage import import_static_snapshot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a versioned sqpack snapshot into SQLite.")
    parser.add_argument("snapshot", type=Path, help="JSON snapshot emitted by LocalDataProbe.")
    parser.add_argument(
        "--database",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "static_catalog.sqlite3",
        help="Destination SQLite catalog.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = import_static_snapshot(args.snapshot, args.database)
    output = asdict(summary)
    output["database_path"] = str(summary.database_path)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
