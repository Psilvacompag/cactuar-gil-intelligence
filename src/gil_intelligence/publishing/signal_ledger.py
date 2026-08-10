from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .signal_candidates import EVERCOLD_CURRENT_ITEM_IDS


@dataclass(frozen=True, slots=True)
class SignalLedgerExportSummary:
    output_path: Path
    current_signals: int
    observations: int
    modules: int


def export_signal_ledger(
    database_path: Path | str,
    output_path: Path | str,
    *,
    dashboard: dict[str, Any],
    market_items: dict[str, Any],
    opportunities: dict[str, Any],
    record: bool = True,
) -> SignalLedgerExportSummary:
    market_snapshot_id = str(
        market_items.get("meta", {}).get("marketSnapshotId")
        or _latest_market_snapshot_id(database_path)
    )
    observed_at = str(market_items.get("meta", {}).get("marketCollectedAt"))
    scope = str(market_items.get("meta", {}).get("scope") or "Cactuar")
    signals = _current_signals(dashboard, market_items, opportunities)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        _create_schema(connection)
        if record:
            with connection:
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO fact_signal_observation (
                        signal_key, market_snapshot_id, module, scope, observed_at,
                        item_id, quality, title, subtitle, state, score,
                        metric_name, metric_value, reference_value, direction,
                        url, reason, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            signal["key"], market_snapshot_id, signal["module"], scope,
                            observed_at, signal.get("itemId"), signal.get("quality"),
                            signal["title"], signal.get("subtitle"), signal["state"],
                            signal["score"], signal["metricName"], signal["metricValue"],
                            signal.get("referenceValue"), signal.get("direction", "HIGHER"),
                            signal["url"], signal["reason"],
                            json.dumps(signal.get("context", {}), ensure_ascii=False, separators=(",", ":")),
                        )
                        for signal in signals
                    ],
                )
        observations = int(
            connection.execute("SELECT COUNT(*) FROM fact_signal_observation").fetchone()[0]
        )
        enriched = [_with_outcome(connection, signal) for signal in signals]
        earliest = connection.execute(
            "SELECT MIN(observed_at) FROM fact_signal_observation"
        ).fetchone()[0]
    finally:
        connection.close()
    by_module: dict[str, int] = {}
    for signal in enriched:
        by_module[signal["module"]] = by_module.get(signal["module"], 0) + 1
    payload = {
        "schemaVersion": 1,
        "kind": "signal-ledger",
        "meta": {
            "scope": scope,
            "marketSnapshotId": market_snapshot_id,
            "marketCollectedAt": observed_at,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "trackingSince": earliest,
            "horizonsDays": [7, 30, 90],
            "source": "Cactuar deterministic signal engine",
        },
        "summary": {
            "currentSignals": len(enriched),
            "observations": observations,
            "modules": by_module,
            "mature7d": sum(signal["outcome"]["return7d"] is not None for signal in enriched),
            "mature30d": sum(signal["outcome"]["return30d"] is not None for signal in enriched),
            "mature90d": sum(signal["outcome"]["return90d"] is not None for signal in enriched),
        },
        "signals": sorted(enriched, key=lambda signal: (signal["score"], signal["metricValue"]), reverse=True),
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return SignalLedgerExportSummary(target.resolve(), len(enriched), observations, len(by_module))


def _current_signals(
    dashboard: dict[str, Any],
    market_items: dict[str, Any],
    opportunities: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    conversions = [item for item in dashboard.get("conversions", []) if item.get("status") == "FRESH" and _positive(item.get("netGilPerCurrency"))]
    conversions.sort(key=lambda item: (item["netGilPerCurrency"], item.get("dailySaleVelocity") or 0), reverse=True)
    for rank, item in enumerate(conversions[:150], start=1):
        key = f"conversion:{item['currencyItemId']}:{item['currencyQuantity']}:{item['rewardItemId']}:{item['rewardQuantity']}:{int(bool(item['rewardIsHq']))}"
        result.append(_signal(
            key=key, module="conversion", item=item, title=item["rewardName"],
            subtitle=f"{item['currencyName']} → {item['rewardName']}", state="ACTIVE",
            score=max(45, 100 - rank // 3), metric_name="netGilPerCurrency",
            metric_value=item["netGilPerCurrency"], reference_value=item.get("marketUnitPrice"),
            url="./", reason=f"{item['netGilPerCurrency']:.2f} gil netos por moneda; ranking #{rank}.",
            context={"currencyItemId": item["currencyItemId"], "currencyName": item["currencyName"], "rank": rank, "velocity": item.get("dailySaleVelocity")},
        ))

    market_candidates: list[dict[str, Any]] = []
    for item in market_items.get("items", []):
        trend = item.get("trend") or {}
        recipe = item.get("recipe") or {}
        active_trend = trend.get("signal") in {"DEMAND_UP", "PRICE_UP", "COOLING"}
        profitable = _positive(recipe.get("profitPerCraft")) and recipe.get("confidence") != "LOW"
        if item.get("status") != "FRESH" or not (active_trend or profitable):
            continue
        score = 45 + min(20, math.log10(float(item.get("dailySaleVelocity") or 0) + 1) * 10)
        score += 18 if trend.get("signal") == "DEMAND_UP" else 12 if trend.get("signal") == "PRICE_UP" else 0
        score += 15 if profitable else 0
        candidate = {**item, "_score": round(min(100, score)), "_profitable": profitable}
        market_candidates.append(candidate)
    market_candidates.sort(key=lambda item: (item["_score"], item.get("estimatedDailyRevenue") or 0), reverse=True)
    for item in market_candidates[:250]:
        trend = item.get("trend") or {}
        recipe = item.get("recipe") or {}
        metric_value = recipe.get("estimatedDailyProfit") if item["_profitable"] else item.get("averageSalePrice")
        if not _positive(metric_value):
            continue
        state = "PROFITABLE" if item["_profitable"] else str(trend.get("signal") or "ACTIVE")
        result.append(_signal(
            key=f"market:{item['itemId']}:{item['quality']}", module="market", item=item,
            title=item["name"], subtitle=item.get("searchCategoryName") or item.get("uiCategoryName"),
            state=state, score=item["_score"],
            metric_name="estimatedDailyProfit" if item["_profitable"] else "averageSalePrice",
            metric_value=metric_value, reference_value=item.get("minListingPrice"), url="./market.html",
            reason=(f"Craft rentable: {recipe.get('profitPerCraft', 0):.0f} gil por craft." if item["_profitable"] else f"Tendencia activa: {state}."),
            context={"velocity": item.get("dailySaleVelocity"), "trend": trend, "craftable": item.get("craftable"), "gatherable": item.get("gatherable")},
        ))

    projection_items = [item for item in market_items.get("items", []) if item.get("itemId") in EVERCOLD_CURRENT_ITEM_IDS and item.get("status") == "FRESH" and _positive(item.get("averageSalePrice"))]
    for item in projection_items:
        trend = item.get("trend") or {}
        velocity_change = float(trend.get("velocityChangeRatio") or 0)
        score = round(max(45, min(100, 68 + max(-12, min(15, velocity_change * 25)) + min(12, math.log10(float(item.get("dailySaleVelocity") or 0) + 1) * 5))))
        result.append(_signal(
            key=f"projection:{item['itemId']}:{item['quality']}", module="projection", item=item,
            title=item["name"], subtitle="Evercold 8.0", state="BULLISH" if score >= 72 else "WATCH",
            score=score, metric_name="averageSalePrice", metric_value=item["averageSalePrice"],
            reference_value=item.get("minListingPrice"), url="./projections.html",
            reason="Equivalente actual de un rol que concentró demanda en lanzamientos anteriores.",
            context={"velocity": item.get("dailySaleVelocity"), "trend": trend, "listingDepth": item.get("listingDepth")},
        ))

    for item in opportunities.get("opportunities", []):
        if not item.get("stockVerified") or not _positive(item.get("estimatedTripProfit")):
            continue
        base_context = {"sourceWorldId": item.get("sourceWorldId"), "sourceWorldName": item.get("sourceWorldName"), "sourceDataCenterName": item.get("sourceDataCenterName"), "quantity": item.get("recommendedQuantity"), "roi": item.get("roi"), "stockVerified": True}
        result.append(_signal(
            key=f"opportunity:{item['itemId']}:{item['quality']}:{item['sourceWorldId']}", module="opportunity", item=item,
            title=item["name"], subtitle=f"{item['sourceWorldName']} → Cactuar", state=item["confidenceBand"],
            score=item["confidenceScore"], metric_name="estimatedTripProfit", metric_value=item["estimatedTripProfit"],
            reference_value=item.get("averagePurchasePrice"), url="./opportunities.html",
            reason=f"Stock verificado; beneficio conservador de {item['estimatedTripProfit']:.0f} gil.", context=base_context,
        ))
        if (item.get("recommendedQuantity") or 0) >= 2 and (item.get("availableUnits") or 0) >= 2:
            snipe_score = round(min(100, item["confidenceScore"] * .8 + min(20, float(item.get("roi") or 0) * 20)))
            result.append(_signal(
                key=f"snipe:{item['itemId']}:{item['quality']}:{item['sourceWorldId']}", module="snipe", item=item,
                title=item["name"], subtitle=f"{item['sourceWorldName']} → Cactuar",
                state="URGENT" if snipe_score >= 75 else "STRONG", score=snipe_score,
                metric_name="estimatedTripProfit", metric_value=item["estimatedTripProfit"],
                reference_value=item.get("averagePurchasePrice"), url="./snipes.html",
                reason=f"Ruta anómala con {item['availableUnits']} unidades verificadas.", context=base_context,
            ))
    return result


def _signal(*, key: str, module: str, item: dict[str, Any], title: str, subtitle: str | None,
            state: str, score: float, metric_name: str, metric_value: float,
            reference_value: float | None, url: str, reason: str,
            context: dict[str, Any]) -> dict[str, Any]:
    return {"key": key, "module": module, "itemId": item.get("itemId") or item.get("rewardItemId"),
            "iconId": item.get("iconId") or item.get("rewardIconId"),
            "quality": item.get("quality") or ("HQ" if item.get("rewardIsHq") else "NQ"),
            "title": title, "subtitle": subtitle, "state": state, "score": round(float(score)),
            "metricName": metric_name, "metricValue": float(metric_value),
            "referenceValue": float(reference_value) if _positive(reference_value) else None,
            "direction": "HIGHER", "url": url, "reason": reason, "context": context}


def _with_outcome(connection: sqlite3.Connection, signal: dict[str, Any]) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT observed_at, metric_value FROM fact_signal_observation WHERE signal_key = ? ORDER BY observed_at, market_snapshot_id",
        (signal["key"],),
    ).fetchall()
    points = [(datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")), float(row["metric_value"])) for row in rows]
    if not points:
        return {**signal, "outcome": _empty_outcome()}
    first_at, initial = points[0]
    current = points[-1][1]
    peak = points[0][1]
    max_drawdown = 0.0
    for _, value in points:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1)
    def horizon(days: int) -> float | None:
        target = first_at + timedelta(days=days)
        point = next((value for at, value in points if at >= target), None)
        return point / initial - 1 if point is not None and initial > 0 else None
    return {**signal, "outcome": {"firstSeenAt": first_at.isoformat(), "observations": len(points),
            "initialValue": initial, "currentValue": current, "change": current / initial - 1 if initial > 0 else None,
            "maximumValue": max(value for _, value in points), "maximumGain": max(value for _, value in points) / initial - 1 if initial > 0 else None,
            "maximumDrawdown": max_drawdown, "return7d": horizon(7), "return30d": horizon(30), "return90d": horizon(90)}}


def _empty_outcome() -> dict[str, Any]:
    return {"firstSeenAt": None, "observations": 0, "initialValue": None, "currentValue": None,
            "change": None, "maximumValue": None, "maximumGain": None, "maximumDrawdown": None,
            "return7d": None, "return30d": None, "return90d": None}


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS fact_signal_observation (
            signal_key TEXT NOT NULL, market_snapshot_id TEXT NOT NULL, module TEXT NOT NULL,
            scope TEXT NOT NULL, observed_at TEXT NOT NULL, item_id INTEGER, quality TEXT,
            title TEXT NOT NULL, subtitle TEXT, state TEXT NOT NULL, score REAL NOT NULL,
            metric_name TEXT NOT NULL, metric_value REAL NOT NULL, reference_value REAL,
            direction TEXT NOT NULL, url TEXT NOT NULL, reason TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY (signal_key, market_snapshot_id)
        );
        CREATE INDEX IF NOT EXISTS idx_signal_observation_module_time
            ON fact_signal_observation(module, observed_at, signal_key);
    """)


def _latest_market_snapshot_id(database_path: Path | str) -> str:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute("SELECT market_snapshot_id FROM market_source_snapshot ORDER BY collected_at DESC, market_snapshot_id DESC LIMIT 1").fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("No market snapshot is available")
    return str(row[0])


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
