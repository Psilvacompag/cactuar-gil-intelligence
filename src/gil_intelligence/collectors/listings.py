from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence

from gil_intelligence.probes.models import JsonResponse


MAX_LISTING_BATCH_SIZE = 100


class JsonClient(Protocol):
    def get_json(self, path: str, query: dict[str, Any] | None = None) -> JsonResponse: ...


@dataclass(frozen=True, slots=True)
class DetailedListingCollection:
    requested_pairs: tuple[tuple[int, int], ...]
    batch_count: int
    items: tuple[dict[str, Any], ...]


def collect_detailed_listings(
    client: JsonClient,
    *,
    candidates: Sequence[dict[str, Any]],
    listings_per_item: int = 20,
    batch_size: int = MAX_LISTING_BATCH_SIZE,
    progress: Callable[[int, int], None] | None = None,
) -> DetailedListingCollection:
    if not 1 <= listings_per_item <= 100:
        raise ValueError("listings_per_item must be between 1 and 100")
    if not 1 <= batch_size <= MAX_LISTING_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_LISTING_BATCH_SIZE}")
    grouped: dict[int, list[int]] = {}
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        item_id = candidate.get("itemId")
        world_id = candidate.get("sourceWorldId")
        if (
            isinstance(item_id, bool)
            or not isinstance(item_id, int)
            or item_id <= 0
            or isinstance(world_id, bool)
            or not isinstance(world_id, int)
            or world_id <= 0
        ):
            raise ValueError("candidates must contain positive itemId and sourceWorldId values")
        pair = (world_id, item_id)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
        grouped.setdefault(world_id, []).append(item_id)
    if not pairs:
        return DetailedListingCollection((), 0, ())
    total_batches = sum(math.ceil(len(item_ids) / batch_size) for item_ids in grouped.values())
    completed = 0
    documents: list[dict[str, Any]] = []
    for world_id in sorted(grouped):
        item_ids = sorted(grouped[world_id])
        for start in range(0, len(item_ids), batch_size):
            batch = item_ids[start : start + batch_size]
            encoded_ids = ",".join(str(item_id) for item_id in batch)
            response = client.get_json(
                f"/api/v2/{world_id}/{encoded_ids}",
                query={"listings": listings_per_item, "entries": 0},
            )
            documents.extend(_normalize_response(response.data, world_id, set(batch)))
            completed += 1
            if progress is not None:
                progress(completed, total_batches)
    return DetailedListingCollection(
        requested_pairs=tuple(pairs),
        batch_count=completed,
        items=tuple(documents),
    )


def _normalize_response(data: Any, world_id: int, requested: set[int]) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("Universalis detailed response must be an object")
    raw_items: list[dict[str, Any]]
    if isinstance(data.get("itemID"), int):
        raw_items = [data]
    else:
        items = data.get("items")
        if not isinstance(items, dict):
            raise ValueError("Universalis multi-item response must contain an items object")
        raw_items = [value for value in items.values() if isinstance(value, dict)]
    normalized: list[dict[str, Any]] = []
    for document in raw_items:
        item_id = document.get("itemID")
        if not isinstance(item_id, int) or item_id not in requested:
            raise ValueError(f"Universalis returned unexpected detailed item ID: {item_id!r}")
        listings = document.get("listings", [])
        if not isinstance(listings, list):
            raise ValueError("Universalis detailed item listings must be a list")
        normalized_listings: list[dict[str, Any]] = []
        for rank, listing in enumerate(listings):
            if not isinstance(listing, dict):
                continue
            price = listing.get("pricePerUnit")
            quantity = listing.get("quantity")
            if (
                isinstance(price, bool)
                or not isinstance(price, int)
                or price <= 0
                or isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity <= 0
            ):
                continue
            normalized_listings.append(
                {
                    "rank": rank,
                    "listingId": listing.get("listingID"),
                    "pricePerUnit": price,
                    "quantity": quantity,
                    "hq": bool(listing.get("hq", False)),
                    "lastReviewTime": listing.get("lastReviewTime"),
                }
            )
        normalized.append(
            {
                "itemId": item_id,
                "worldId": world_id,
                "lastUploadTime": document.get("lastUploadTime"),
                "listings": normalized_listings,
            }
        )
    return normalized
