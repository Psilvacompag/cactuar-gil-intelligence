from __future__ import annotations

import math
from statistics import median
from typing import Any


EVERCOLD_CURRENT_ITEM_IDS = frozenset(
    (*range(8, 20), *range(41757, 41770), 27960)
)


def signal_depth_candidates(
    market: dict[str, Any],
    history: dict[str, Any],
    *,
    home_world_id: int = 79,
    snipe_limit: int = 40,
) -> list[dict[str, int]]:
    """Reserve detailed listing coverage for projections and likely snipes."""
    items = market.get("items") if isinstance(market.get("items"), list) else []
    series = history.get("series") if isinstance(history.get("series"), list) else []
    history_by_key = {
        document.get("key"): document
        for document in series
        if isinstance(document, dict) and isinstance(document.get("key"), str)
    }
    projection_ids = {
        int(item["itemId"])
        for item in items
        if _positive_int(item.get("itemId"))
        and item["itemId"] in EVERCOLD_CURRENT_ITEM_IDS
        and item.get("status") == "FRESH"
    }
    ranked_snipes: list[tuple[float, int]] = []
    for item in items:
        item_id = item.get("itemId")
        quality = item.get("quality")
        current = item.get("minListingPrice")
        velocity = item.get("dailySaleVelocity")
        if (
            not _positive_int(item_id)
            or quality not in {"NQ", "HQ"}
            or item.get("status") != "FRESH"
            or not _positive_number(current)
            or not _positive_number(velocity)
        ):
            continue
        document = history_by_key.get(f"{item_id}:{quality}")
        points = document.get("points") if isinstance(document, dict) else None
        if not isinstance(points, list) or len(points) < 3:
            continue
        previous_listings = [
            point.get("minListingPrice")
            for point in points[:-1]
            if isinstance(point, dict) and _positive_number(point.get("minListingPrice"))
        ]
        sale_prices = [
            point.get("averageSalePrice")
            for point in points
            if isinstance(point, dict) and _positive_number(point.get("averageSalePrice"))
        ]
        references = []
        if previous_listings:
            references.append(float(median(previous_listings)))
        if sale_prices:
            references.append(float(median(sale_prices)))
        if not references:
            continue
        reference = min(references)
        discount = 1 - float(current) / reference
        volatility = (document.get("trend") or {}).get("priceVolatility")
        volatility = float(volatility) if _number(volatility) else 1.0
        profit = reference * 0.95 - float(current)
        threshold = 0.50 if volatility > 0.45 else 0.25
        if discount < threshold or profit < max(100, float(current) * 0.20):
            continue
        rank = discount * 100 + math.log10(float(velocity) + 1) * 10
        ranked_snipes.append((rank, int(item_id)))

    snipe_ids: list[int] = []
    seen = set(projection_ids)
    for _, item_id in sorted(ranked_snipes, reverse=True):
        if item_id in seen:
            continue
        seen.add(item_id)
        snipe_ids.append(item_id)
        if len(snipe_ids) >= max(0, snipe_limit):
            break
    return [
        {"itemId": item_id, "sourceWorldId": home_world_id}
        for item_id in [*sorted(projection_ids), *snipe_ids]
    ]


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive_number(value: object) -> bool:
    return _number(value) and float(value) > 0


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
