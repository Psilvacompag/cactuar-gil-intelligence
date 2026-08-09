from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ImportSummary:
    database_path: Path
    snapshot_id: str
    game_version: str
    assets: int
    shops: int
    offers: int
    costs: int
    rewards: int
    requirements: int


def import_static_snapshot(snapshot_path: Path | str, database_path: Path | str) -> ImportSummary:
    source_path = Path(snapshot_path)
    target_path = Path(database_path)
    with source_path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    normalized = _validate_snapshot(payload)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_id = (
        f"{normalized['source']}:{normalized['gameVersion']}:"
        f"schema-{normalized['schemaVersion']}"
    )
    connection = sqlite3.connect(target_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        with connection:
            if _table_exists(connection, "currency_valuation_run"):
                connection.execute(
                    "DELETE FROM currency_valuation_run WHERE static_snapshot_id = ?",
                    (snapshot_id,),
                )
            connection.execute("DELETE FROM source_snapshot WHERE snapshot_id = ?", (snapshot_id,))
            connection.execute(
                """
                INSERT INTO source_snapshot (
                    snapshot_id, source, game_version, schema_version, extracted_at, imported_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    snapshot_id,
                    normalized["source"],
                    normalized["gameVersion"],
                    normalized["schemaVersion"],
                    normalized["extractedAt"],
                ),
            )
            connection.executemany(
                """
                INSERT INTO dim_asset (
                    snapshot_id, item_id, name, marketable_candidate
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        row["itemId"],
                        row.get("name"),
                        int(row["marketableCandidate"]),
                    )
                    for row in normalized["assets"]
                ),
            )
            connection.executemany(
                """
                INSERT INTO dim_shop (
                    snapshot_id, shop_id, source_sheet, name, use_currency_type
                ) VALUES (?, ?, 'SpecialShop', ?, ?)
                """,
                (
                    (snapshot_id, row["shopId"], row.get("name"), row["useCurrencyType"])
                    for row in normalized["shops"]
                ),
            )

            costs_by_offer = _group_by_offer(normalized["costs"])
            rewards_by_offer = _group_by_offer(normalized["rewards"])
            connection.executemany(
                """
                INSERT INTO dim_shop_offer (
                    snapshot_id, shop_id, offer_index, source_subrow_key, parse_status, raw_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        row["shopId"],
                        row["offerIndex"],
                        row["sourceSubrowKey"],
                        row["parseStatus"],
                        _offer_hash(row, costs_by_offer, rewards_by_offer),
                    )
                    for row in normalized["offers"]
                ),
            )
            connection.executemany(
                """
                INSERT INTO bridge_offer_cost (
                    snapshot_id, shop_id, offer_index, cost_index, raw_item_id,
                    item_id, quantity, cost_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        row["shopId"],
                        row["offerIndex"],
                        row["costIndex"],
                        row["rawItemId"],
                        row.get("itemId"),
                        row["quantity"],
                        row["costType"],
                    )
                    for row in normalized["costs"]
                ),
            )
            connection.executemany(
                """
                INSERT INTO bridge_offer_reward (
                    snapshot_id, shop_id, offer_index, reward_index, item_id, quantity, is_hq
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        row["shopId"],
                        row["offerIndex"],
                        row["rewardIndex"],
                        row["itemId"],
                        row["quantity"],
                        int(row.get("isHq", False)),
                    )
                    for row in normalized["rewards"]
                ),
            )
            connection.executemany(
                """
                INSERT INTO bridge_offer_requirement (
                    snapshot_id, shop_id, offer_index, requirement_index,
                    requirement_type, requirement_value
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                _requirement_rows(snapshot_id, normalized["requirements"]),
            )
            coverage = normalized["coverage"]
            connection.execute(
                """
                INSERT INTO shop_coverage_audit (
                    snapshot_id, source_sheet, source_rows, offers_emitted,
                    rows_ignored, rows_failed
                ) VALUES (?, 'SpecialShop', ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    coverage["sourceRows"],
                    coverage["offersEmitted"],
                    coverage["rowsIgnored"],
                    coverage["rowsFailed"],
                ),
            )
    finally:
        connection.close()

    return ImportSummary(
        database_path=target_path.resolve(),
        snapshot_id=snapshot_id,
        game_version=normalized["gameVersion"],
        assets=len(normalized["assets"]),
        shops=len(normalized["shops"]),
        offers=len(normalized["offers"]),
        costs=len(normalized["costs"]),
        rewards=len(normalized["rewards"]),
        requirements=len(normalized["requirements"]),
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_snapshot (
            snapshot_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            game_version TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            extracted_at TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dim_asset (
            snapshot_id TEXT NOT NULL,
            item_id INTEGER NOT NULL CHECK (item_id > 0),
            name TEXT,
            marketable_candidate INTEGER NOT NULL CHECK (marketable_candidate IN (0, 1)),
            PRIMARY KEY (snapshot_id, item_id),
            FOREIGN KEY (snapshot_id) REFERENCES source_snapshot(snapshot_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dim_shop (
            snapshot_id TEXT NOT NULL,
            shop_id INTEGER NOT NULL CHECK (shop_id > 0),
            source_sheet TEXT NOT NULL,
            name TEXT,
            use_currency_type INTEGER NOT NULL,
            PRIMARY KEY (snapshot_id, shop_id),
            FOREIGN KEY (snapshot_id) REFERENCES source_snapshot(snapshot_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dim_shop_offer (
            snapshot_id TEXT NOT NULL,
            shop_id INTEGER NOT NULL,
            offer_index INTEGER NOT NULL CHECK (offer_index >= 0),
            source_subrow_key TEXT NOT NULL,
            parse_status TEXT NOT NULL,
            raw_hash TEXT NOT NULL,
            PRIMARY KEY (snapshot_id, shop_id, offer_index),
            UNIQUE (snapshot_id, source_subrow_key),
            FOREIGN KEY (snapshot_id, shop_id)
                REFERENCES dim_shop(snapshot_id, shop_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bridge_offer_cost (
            snapshot_id TEXT NOT NULL,
            shop_id INTEGER NOT NULL,
            offer_index INTEGER NOT NULL,
            cost_index INTEGER NOT NULL CHECK (cost_index >= 0),
            raw_item_id INTEGER NOT NULL CHECK (raw_item_id >= 0),
            item_id INTEGER,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            cost_type INTEGER NOT NULL,
            PRIMARY KEY (snapshot_id, shop_id, offer_index, cost_index),
            FOREIGN KEY (snapshot_id, shop_id, offer_index)
                REFERENCES dim_shop_offer(snapshot_id, shop_id, offer_index) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id, item_id)
                REFERENCES dim_asset(snapshot_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS bridge_offer_reward (
            snapshot_id TEXT NOT NULL,
            shop_id INTEGER NOT NULL,
            offer_index INTEGER NOT NULL,
            reward_index INTEGER NOT NULL CHECK (reward_index >= 0),
            item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            is_hq INTEGER NOT NULL DEFAULT 0 CHECK (is_hq IN (0, 1)),
            PRIMARY KEY (snapshot_id, shop_id, offer_index, reward_index),
            FOREIGN KEY (snapshot_id, shop_id, offer_index)
                REFERENCES dim_shop_offer(snapshot_id, shop_id, offer_index) ON DELETE CASCADE,
            FOREIGN KEY (snapshot_id, item_id)
                REFERENCES dim_asset(snapshot_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS bridge_offer_requirement (
            snapshot_id TEXT NOT NULL,
            shop_id INTEGER NOT NULL,
            offer_index INTEGER,
            requirement_index INTEGER NOT NULL CHECK (requirement_index >= 0),
            requirement_type TEXT NOT NULL,
            requirement_value INTEGER NOT NULL CHECK (requirement_value > 0),
            PRIMARY KEY (snapshot_id, shop_id, offer_index, requirement_index),
            FOREIGN KEY (snapshot_id, shop_id)
                REFERENCES dim_shop(snapshot_id, shop_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS shop_coverage_audit (
            snapshot_id TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            source_rows INTEGER NOT NULL CHECK (source_rows >= 0),
            offers_emitted INTEGER NOT NULL CHECK (offers_emitted >= 0),
            rows_ignored INTEGER NOT NULL CHECK (rows_ignored >= 0),
            rows_failed INTEGER NOT NULL CHECK (rows_failed >= 0),
            PRIMARY KEY (snapshot_id, source_sheet),
            FOREIGN KEY (snapshot_id) REFERENCES source_snapshot(snapshot_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_offer_cost_item
            ON bridge_offer_cost(snapshot_id, item_id);
        CREATE INDEX IF NOT EXISTS idx_offer_reward_item
            ON bridge_offer_reward(snapshot_id, item_id);
        """
    )
    _ensure_column(
        connection,
        "bridge_offer_reward",
        "is_hq",
        "INTEGER NOT NULL DEFAULT 0 CHECK (is_hq IN (0, 1))",
    )


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _validate_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Snapshot root must be a JSON object")
    required = {
        "schemaVersion",
        "source",
        "gameVersion",
        "extractedAt",
        "assets",
        "shops",
        "offers",
        "costs",
        "rewards",
        "requirements",
        "coverage",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"Snapshot is missing fields: {', '.join(missing)}")
    if payload["schemaVersion"] != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported snapshot schema {payload['schemaVersion']}; "
            f"expected {SUPPORTED_SCHEMA_VERSION}"
        )
    for name in ("source", "gameVersion", "extractedAt"):
        if not isinstance(payload[name], str) or not payload[name]:
            raise ValueError(f"{name} must be a non-empty string")
    for name in ("assets", "shops", "offers", "costs", "rewards", "requirements"):
        if not isinstance(payload[name], list) or not all(isinstance(row, dict) for row in payload[name]):
            raise ValueError(f"{name} must be a list of objects")
    if not isinstance(payload["coverage"], dict):
        raise ValueError("coverage must be an object")
    for name in ("costs", "rewards"):
        for index, row in enumerate(payload[name]):
            quantity = row.get("quantity")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                raise ValueError(f"{name}[{index}].quantity must be a positive integer")
    return payload


def _group_by_offer(rows: Iterable[dict[str, Any]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["shopId"], row["offerIndex"]), []).append(row)
    return grouped


def _offer_hash(
    offer: dict[str, Any],
    costs: dict[tuple[int, int], list[dict[str, Any]]],
    rewards: dict[tuple[int, int], list[dict[str, Any]]],
) -> str:
    key = (offer["shopId"], offer["offerIndex"])
    canonical = json.dumps(
        {
            "offer": offer,
            "costs": costs.get(key, []),
            "rewards": rewards.get(key, []),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _requirement_rows(
    snapshot_id: str, requirements: Iterable[dict[str, Any]]
) -> Iterable[tuple[Any, ...]]:
    indices: dict[tuple[int, int | None], int] = {}
    for row in requirements:
        key = (row["shopId"], row.get("offerIndex"))
        requirement_index = indices.get(key, 0)
        indices[key] = requirement_index + 1
        yield (
            snapshot_id,
            row["shopId"],
            row.get("offerIndex"),
            requirement_index,
            row["requirementType"],
            row["requirementValue"],
        )
