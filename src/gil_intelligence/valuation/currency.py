from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PRICE_COLUMNS = {
    "MIN_LISTING": "min_listing_price",
    "MEDIAN_LISTING": "median_listing_price",
    "RECENT_AVG_SALE": "average_sale_price",
}

# Currency conversions are ranked with the lowest currently actionable listing.
# Universalis' recent average can be heavily skewed by accidental or manipulated
# sales, so it remains available for analysis but is not the production default.
DEFAULT_CURRENCY_PRICE_BASIS = "MIN_LISTING"


@dataclass(frozen=True, slots=True)
class CurrencyValuationSummary:
    database_path: Path
    valuation_run_id: str
    static_snapshot_id: str
    market_snapshot_id: str
    scope: str
    market_scope_level: str
    price_basis: str
    fee_rate: float
    valued_at: str
    total_offers: int
    parsed_offers: int
    incomplete_offers: int
    multiple_cost_offers: int
    multiple_reward_offers: int
    gil_cost_offers: int
    eligible_offers: int
    valued_offers: int
    fresh_offers: int
    stale_offers: int
    no_market_data_offers: int
    not_tradeable_offers: int


def build_currency_valuations(
    database_path: Path | str,
    *,
    scope: str,
    price_basis: str = DEFAULT_CURRENCY_PRICE_BASIS,
    fee_rate: float = 0.05,
    freshness_hours: float = 24.0,
    static_snapshot_id: str | None = None,
    market_snapshot_id: str | None = None,
    as_of: datetime | None = None,
) -> CurrencyValuationSummary:
    """Cross one static shop catalog with one aggregate market snapshot."""
    if price_basis not in PRICE_COLUMNS:
        raise ValueError(f"Unsupported price basis: {price_basis}")
    if not 0 <= fee_rate < 1:
        raise ValueError("fee_rate must be between 0 (inclusive) and 1 (exclusive)")
    if freshness_hours <= 0:
        raise ValueError("freshness_hours must be positive")
    if not scope.strip():
        raise ValueError("scope must be a non-empty string")

    target_path = Path(database_path)
    connection = sqlite3.connect(target_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        selected_static = static_snapshot_id or _select_static_snapshot(connection)
        selected_market = market_snapshot_id or _select_market_snapshot(connection, scope)
        market_source = connection.execute(
            """
            SELECT scope, collected_at
            FROM market_source_snapshot
            WHERE market_snapshot_id = ?
            """,
            (selected_market,),
        ).fetchone()
        if market_source is None:
            raise ValueError(f"Unknown market snapshot: {selected_market}")
        if market_source["scope"].casefold() != scope.casefold():
            raise ValueError(
                f"Market snapshot scope {market_source['scope']!r} does not match {scope!r}"
            )
        valued_at = as_of or datetime.now(timezone.utc)
        if valued_at.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        valued_at = valued_at.astimezone(timezone.utc)
        freshness_cutoff = valued_at - timedelta(hours=freshness_hours)
        market_scope_level = _market_scope_level(connection, selected_market)

        counts = _offer_counts(connection, selected_static)
        rows = _eligible_rows(
            connection,
            selected_static,
            selected_market,
            market_scope_level,
        )
        _create_schema(connection)

        run_key = "\0".join(
            (
                selected_static,
                selected_market,
                price_basis,
                market_scope_level,
                f"{fee_rate:.12g}",
                f"{freshness_hours:.12g}",
                valued_at.isoformat(),
            )
        )
        run_id = f"currency:{hashlib.sha256(run_key.encode('utf-8')).hexdigest()[:24]}"
        valuations: list[tuple[Any, ...]] = []
        status_counts = {
            "FRESH": 0,
            "STALE": 0,
            "NO_MARKET_DATA": 0,
            "NOT_TRADEABLE": 0,
        }
        price_column = PRICE_COLUMNS[price_basis]

        for row in rows:
            unit_price = row[price_column]
            if not row["marketable_candidate"]:
                status = "NOT_TRADEABLE"
            elif unit_price is None:
                status = "NO_MARKET_DATA"
            else:
                latest_upload = (
                    datetime.fromisoformat(row["latest_upload_at"])
                    if row["latest_upload_at"] is not None
                    else None
                )
                status = (
                    "FRESH"
                    if latest_upload is not None and latest_upload >= freshness_cutoff
                    else "STALE"
                )
            status_counts[status] += 1

            gross_total = (
                float(unit_price) * row["reward_quantity"] if unit_price is not None else None
            )
            fee_gil = gross_total * fee_rate if gross_total is not None else None
            net_total = gross_total - fee_gil if gross_total is not None else None
            divisor = row["currency_quantity"]
            gross_per_currency = gross_total / divisor if gross_total is not None else None
            net_per_currency = net_total / divisor if net_total is not None else None
            valuations.append(
                (
                    run_id,
                    selected_static,
                    selected_market,
                    row["shop_id"],
                    row["offer_index"],
                    row["currency_item_id"],
                    row["currency_name"],
                    divisor,
                    row["reward_item_id"],
                    row["reward_name"],
                    row["reward_quantity"],
                    row["reward_is_hq"],
                    price_basis,
                    unit_price,
                    gross_total,
                    fee_rate,
                    fee_gil,
                    net_total,
                    gross_per_currency,
                    net_per_currency,
                    row["daily_sale_velocity"],
                    row["latest_upload_at"],
                    status,
                )
            )

        with connection:
            connection.execute("DELETE FROM currency_valuation_run WHERE valuation_run_id = ?", (run_id,))
            connection.execute(
                """
                INSERT INTO currency_valuation_run (
                    valuation_run_id, static_snapshot_id, market_snapshot_id, scope,
                    price_basis, market_scope_level, fee_rate, freshness_hours, created_at
                    , valued_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    run_id,
                    selected_static,
                    selected_market,
                    scope,
                    price_basis,
                    market_scope_level,
                    fee_rate,
                    freshness_hours,
                    valued_at.isoformat(),
                ),
            )
            connection.executemany(
                """
                INSERT INTO currency_market_valuation (
                    valuation_run_id, static_snapshot_id, market_snapshot_id,
                    shop_id, offer_index, currency_item_id, currency_name,
                    currency_quantity, reward_item_id, reward_name, reward_quantity,
                    reward_is_hq, price_basis, market_unit_price, gross_total_gil,
                    fee_rate, market_fee_gil, net_total_gil, gross_gil_per_currency,
                    net_gil_per_currency, daily_sale_velocity, latest_upload_at,
                    valuation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                valuations,
            )
    finally:
        connection.close()

    valued = status_counts["FRESH"] + status_counts["STALE"]
    return CurrencyValuationSummary(
        database_path=target_path.resolve(),
        valuation_run_id=run_id,
        static_snapshot_id=selected_static,
        market_snapshot_id=selected_market,
        scope=scope,
        market_scope_level=market_scope_level,
        price_basis=price_basis,
        fee_rate=fee_rate,
        valued_at=valued_at.isoformat(),
        total_offers=counts["total"],
        parsed_offers=counts["parsed"],
        incomplete_offers=counts["incomplete"],
        multiple_cost_offers=counts["multiple_cost"],
        multiple_reward_offers=counts["multiple_reward"],
        gil_cost_offers=counts["gil_cost"],
        eligible_offers=len(rows),
        valued_offers=valued,
        fresh_offers=status_counts["FRESH"],
        stale_offers=status_counts["STALE"],
        no_market_data_offers=status_counts["NO_MARKET_DATA"],
        not_tradeable_offers=status_counts["NOT_TRADEABLE"],
    )


def get_top_currency_conversions(
    database_path: Path | str,
    valuation_run_id: str,
    *,
    limit: int = 20,
    currency_query: str | None = None,
    fresh_only: bool = True,
    minimum_daily_velocity: float = 0.1,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if minimum_daily_velocity < 0:
        raise ValueError("minimum_daily_velocity must be non-negative")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        query = """
            SELECT currency_item_id, currency_name, currency_quantity,
                   reward_item_id, reward_name, reward_quantity, reward_is_hq,
                   market_unit_price, net_gil_per_currency, daily_sale_velocity,
                   latest_upload_at, valuation_status, shop_id, offer_index
            FROM currency_market_valuation
            WHERE valuation_run_id = ?
              AND valuation_status IN ('FRESH', 'STALE')
              AND COALESCE(daily_sale_velocity, 0) >= ?
        """
        parameters: list[Any] = [valuation_run_id, minimum_daily_velocity]
        if fresh_only:
            query += " AND valuation_status = 'FRESH'"
        if currency_query:
            query += " AND currency_name LIKE ?"
            parameters.append(f"%{currency_query}%")
        query += " ORDER BY net_gil_per_currency DESC, daily_sale_velocity DESC"
        conversions: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for row in connection.execute(query, parameters):
            conversion = dict(row)
            signature = (
                conversion["currency_item_id"],
                conversion["currency_quantity"],
                conversion["reward_item_id"],
                conversion["reward_quantity"],
                conversion["reward_is_hq"],
            )
            if signature in seen:
                continue
            seen.add(signature)
            conversions.append(conversion)
            if len(conversions) >= limit:
                break
        return conversions
    finally:
        connection.close()


def _select_static_snapshot(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT snapshot_id FROM source_snapshot ORDER BY extracted_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No static snapshot is available")
    return row[0]


def _select_market_snapshot(connection: sqlite3.Connection, scope: str) -> str:
    row = connection.execute(
        """
        SELECT market_snapshot_id
        FROM market_source_snapshot
        WHERE lower(scope) = lower(?)
        ORDER BY requested_item_count DESC, collected_at DESC
        LIMIT 1
        """,
        (scope,),
    ).fetchone()
    if row is None:
        raise ValueError(f"No market snapshot is available for scope {scope!r}")
    return row[0]


def _market_scope_level(connection: sqlite3.Connection, market_snapshot_id: str) -> str:
    has_world = connection.execute(
        """
        SELECT 1
        FROM fact_market_aggregate_snapshot
        WHERE market_snapshot_id = ? AND scope_level = 'WORLD'
        LIMIT 1
        """,
        (market_snapshot_id,),
    ).fetchone()
    return "WORLD" if has_world is not None else "DC"


def _offer_counts(connection: sqlite3.Connection, snapshot_id: str) -> dict[str, int]:
    row = connection.execute(
        """
        WITH costs AS (
            SELECT shop_id, offer_index, COUNT(*) AS component_count,
                   MAX(CASE WHEN item_id = 1 THEN 1 ELSE 0 END) AS has_gil
            FROM bridge_offer_cost
            WHERE snapshot_id = ?
            GROUP BY shop_id, offer_index
        ), rewards AS (
            SELECT shop_id, offer_index, COUNT(*) AS component_count
            FROM bridge_offer_reward
            WHERE snapshot_id = ?
            GROUP BY shop_id, offer_index
        )
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN offer.parse_status = 'PARSED' THEN 1 ELSE 0 END) AS parsed,
            SUM(CASE WHEN offer.parse_status <> 'PARSED' THEN 1 ELSE 0 END) AS incomplete,
            SUM(CASE WHEN COALESCE(costs.component_count, 0) > 1 THEN 1 ELSE 0 END) AS multiple_cost,
            SUM(CASE WHEN COALESCE(rewards.component_count, 0) > 1 THEN 1 ELSE 0 END) AS multiple_reward,
            SUM(CASE WHEN costs.component_count = 1 AND costs.has_gil = 1 THEN 1 ELSE 0 END) AS gil_cost
        FROM dim_shop_offer AS offer
        LEFT JOIN costs USING (shop_id, offer_index)
        LEFT JOIN rewards USING (shop_id, offer_index)
        WHERE offer.snapshot_id = ?
        """,
        (snapshot_id, snapshot_id, snapshot_id),
    ).fetchone()
    return {name: int(row[name] or 0) for name in row.keys()}


def _eligible_rows(
    connection: sqlite3.Connection,
    static_snapshot_id: str,
    market_snapshot_id: str,
    market_scope_level: str,
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            WITH cost_counts AS (
                SELECT shop_id, offer_index, COUNT(*) AS component_count
                FROM bridge_offer_cost
                WHERE snapshot_id = ?
                GROUP BY shop_id, offer_index
            ), reward_counts AS (
                SELECT shop_id, offer_index, COUNT(*) AS component_count
                FROM bridge_offer_reward
                WHERE snapshot_id = ?
                GROUP BY shop_id, offer_index
            ), freshness AS (
                SELECT item_id, MAX(uploaded_at) AS latest_upload_at
                FROM fact_data_freshness
                WHERE market_snapshot_id = ?
                GROUP BY item_id
            )
            SELECT
                offer.shop_id,
                offer.offer_index,
                cost.item_id AS currency_item_id,
                currency.name AS currency_name,
                cost.quantity AS currency_quantity,
                reward.item_id AS reward_item_id,
                reward_asset.name AS reward_name,
                reward.quantity AS reward_quantity,
                reward.is_hq AS reward_is_hq,
                reward_asset.marketable_candidate,
                market.min_listing_price,
                market.median_listing_price,
                market.average_sale_price,
                market.daily_sale_velocity,
                freshness.latest_upload_at
            FROM dim_shop_offer AS offer
            JOIN cost_counts USING (shop_id, offer_index)
            JOIN reward_counts USING (shop_id, offer_index)
            JOIN bridge_offer_cost AS cost
                ON cost.snapshot_id = offer.snapshot_id
                AND cost.shop_id = offer.shop_id
                AND cost.offer_index = offer.offer_index
            JOIN bridge_offer_reward AS reward
                ON reward.snapshot_id = offer.snapshot_id
                AND reward.shop_id = offer.shop_id
                AND reward.offer_index = offer.offer_index
            JOIN dim_asset AS currency
                ON currency.snapshot_id = offer.snapshot_id
                AND currency.item_id = cost.item_id
            JOIN dim_asset AS reward_asset
                ON reward_asset.snapshot_id = offer.snapshot_id
                AND reward_asset.item_id = reward.item_id
            LEFT JOIN fact_market_aggregate_snapshot AS market
                ON market.market_snapshot_id = ?
                AND market.item_id = reward.item_id
                AND market.quality = CASE WHEN reward.is_hq = 1 THEN 'HQ' ELSE 'NQ' END
                AND market.scope_level = ?
            LEFT JOIN freshness ON freshness.item_id = reward.item_id
            WHERE offer.snapshot_id = ?
              AND offer.parse_status = 'PARSED'
              AND cost_counts.component_count = 1
              AND reward_counts.component_count = 1
              AND cost.item_id <> 1
            """,
            (
                static_snapshot_id,
                static_snapshot_id,
                market_snapshot_id,
                market_snapshot_id,
                market_scope_level,
                static_snapshot_id,
            ),
        )
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS currency_valuation_run (
            valuation_run_id TEXT PRIMARY KEY,
            static_snapshot_id TEXT NOT NULL,
            market_snapshot_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            price_basis TEXT NOT NULL,
            market_scope_level TEXT,
            fee_rate REAL NOT NULL,
            freshness_hours REAL NOT NULL,
            created_at TEXT NOT NULL,
            valued_at TEXT,
            FOREIGN KEY (static_snapshot_id)
                REFERENCES source_snapshot(snapshot_id) ON DELETE CASCADE,
            FOREIGN KEY (market_snapshot_id)
                REFERENCES market_source_snapshot(market_snapshot_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS currency_market_valuation (
            valuation_run_id TEXT NOT NULL,
            static_snapshot_id TEXT NOT NULL,
            market_snapshot_id TEXT NOT NULL,
            shop_id INTEGER NOT NULL,
            offer_index INTEGER NOT NULL,
            currency_item_id INTEGER NOT NULL,
            currency_name TEXT,
            currency_quantity INTEGER NOT NULL CHECK (currency_quantity > 0),
            reward_item_id INTEGER NOT NULL,
            reward_name TEXT,
            reward_quantity INTEGER NOT NULL CHECK (reward_quantity > 0),
            reward_is_hq INTEGER NOT NULL CHECK (reward_is_hq IN (0, 1)),
            price_basis TEXT NOT NULL,
            market_unit_price REAL,
            gross_total_gil REAL,
            fee_rate REAL NOT NULL,
            market_fee_gil REAL,
            net_total_gil REAL,
            gross_gil_per_currency REAL,
            net_gil_per_currency REAL,
            daily_sale_velocity REAL,
            latest_upload_at TEXT,
            valuation_status TEXT NOT NULL,
            PRIMARY KEY (valuation_run_id, shop_id, offer_index),
            FOREIGN KEY (valuation_run_id)
                REFERENCES currency_valuation_run(valuation_run_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_currency_valuation_ranking
            ON currency_market_valuation(
                valuation_run_id, valuation_status, net_gil_per_currency DESC
            );
        CREATE INDEX IF NOT EXISTS idx_currency_valuation_currency
            ON currency_market_valuation(valuation_run_id, currency_item_id);
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(currency_valuation_run)")}
    if "valued_at" not in columns:
        connection.execute("ALTER TABLE currency_valuation_run ADD COLUMN valued_at TEXT")
    if "market_scope_level" not in columns:
        connection.execute(
            "ALTER TABLE currency_valuation_run ADD COLUMN market_scope_level TEXT"
        )
