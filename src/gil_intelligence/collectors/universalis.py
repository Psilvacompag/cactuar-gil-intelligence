from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence
from urllib.parse import quote

from gil_intelligence.probes.models import JsonResponse


MAX_AGGREGATED_BATCH_SIZE = 100


class JsonClient(Protocol):
    def get_json(self, path: str, query: dict[str, Any] | None = None) -> JsonResponse: ...


@dataclass(frozen=True, slots=True)
class AggregatedCollection:
    scope: str
    requested_item_ids: tuple[int, ...]
    batch_count: int
    payload: dict[str, list[Any]]


def collect_aggregated_market(
    client: JsonClient,
    *,
    scope: str,
    item_ids: Sequence[int],
    batch_size: int = MAX_AGGREGATED_BATCH_SIZE,
    progress: Callable[[int, int], None] | None = None,
) -> AggregatedCollection:
    """Fetch Universalis aggregates in bounded, deterministic batches."""
    if not scope.strip():
        raise ValueError("scope must be a non-empty string")
    if not 1 <= batch_size <= MAX_AGGREGATED_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_AGGREGATED_BATCH_SIZE}")

    normalized_ids = tuple(dict.fromkeys(item_ids))
    if not normalized_ids:
        raise ValueError("item_ids must contain at least one item")
    if any(isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0 for item_id in normalized_ids):
        raise ValueError("item_ids must contain positive integers")

    encoded_scope = quote(scope, safe="")
    results: list[Any] = []
    failed_items: list[Any] = []
    batch_count = 0
    total_batches = math.ceil(len(normalized_ids) / batch_size)
    requested = set(normalized_ids)

    for start in range(0, len(normalized_ids), batch_size):
        batch = normalized_ids[start : start + batch_size]
        encoded_ids = ",".join(str(item_id) for item_id in batch)
        response = client.get_json(f"/api/v2/aggregated/{encoded_scope}/{encoded_ids}")
        if not isinstance(response.data, dict):
            raise ValueError("Universalis aggregated response must be an object")
        batch_results = response.data.get("results")
        batch_failures = response.data.get("failedItems")
        if not isinstance(batch_results, list) or not isinstance(batch_failures, list):
            raise ValueError("Universalis aggregated response must contain results and failedItems lists")
        results.extend(batch_results)
        failed_items.extend(batch_failures)
        batch_count += 1
        if progress is not None:
            progress(batch_count, total_batches)

    returned_ids = {
        row.get("itemId")
        for row in results
        if isinstance(row, dict) and isinstance(row.get("itemId"), int)
    }
    unexpected = sorted(item_id for item_id in returned_ids if item_id not in requested)
    if unexpected:
        raise ValueError(f"Universalis returned unexpected item IDs: {unexpected}")

    return AggregatedCollection(
        scope=scope,
        requested_item_ids=normalized_ids,
        batch_count=batch_count,
        payload={"results": results, "failedItems": failed_items},
    )
