from __future__ import annotations

from math import ceil
from typing import Any


def estimate_market_request_budget(
    marketable_items: int,
    *,
    candidate_items: int = 1_000,
    batch_size: int = 100,
    global_snapshots_per_day: int = 4,
    candidate_snapshots_per_day: int = 48,
    safe_requests_per_second: float = 2.0,
) -> dict[str, Any]:
    if marketable_items < 0 or candidate_items < 0:
        raise ValueError("item counts cannot be negative")
    if batch_size <= 0 or safe_requests_per_second <= 0:
        raise ValueError("batch_size and safe_requests_per_second must be positive")

    full_snapshot_requests = ceil(marketable_items / batch_size)
    candidate_snapshot_requests = ceil(min(candidate_items, marketable_items) / batch_size)
    full_daily_requests = full_snapshot_requests * global_snapshots_per_day
    candidate_daily_requests = candidate_snapshot_requests * candidate_snapshots_per_day
    total_daily_requests = full_daily_requests + candidate_daily_requests

    return {
        "marketable_items": marketable_items,
        "batch_size": batch_size,
        "safe_requests_per_second": safe_requests_per_second,
        "full_snapshot_requests": full_snapshot_requests,
        "full_snapshot_minimum_seconds": round(full_snapshot_requests / safe_requests_per_second, 2),
        "full_daily_requests": full_daily_requests,
        "candidate_items": min(candidate_items, marketable_items),
        "candidate_daily_requests": candidate_daily_requests,
        "total_daily_requests": total_daily_requests,
        "total_daily_request_time_minutes": round(
            total_daily_requests / safe_requests_per_second / 60,
            2,
        ),
        "note": "Request time is distributed across the day; it is not continuous load.",
    }

