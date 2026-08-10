from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


TABLES: dict[str, dict[str, Any]] = {
    "market_runs": {
        "schema": (
            ("market_snapshot_id", "STRING", "REQUIRED"),
            ("scope", "STRING", "REQUIRED"),
            ("collected_at", "TIMESTAMP", "REQUIRED"),
            ("source_url", "STRING", "NULLABLE"),
            ("requested_item_count", "INTEGER", "NULLABLE"),
            ("result_item_count", "INTEGER", "NULLABLE"),
            ("failed_item_count", "INTEGER", "NULLABLE"),
            ("request_count", "INTEGER", "NULLABLE"),
            ("collection_elapsed_seconds", "FLOAT", "NULLABLE"),
            ("payload_sha256", "STRING", "NULLABLE"),
            ("valuation_run_id", "STRING", "NULLABLE"),
            ("static_snapshot_id", "STRING", "NULLABLE"),
            ("valued_at", "TIMESTAMP", "NULLABLE"),
            ("market_scope_level", "STRING", "NULLABLE"),
            ("price_basis", "STRING", "NULLABLE"),
            ("fee_rate", "FLOAT", "NULLABLE"),
            ("freshness_hours", "FLOAT", "NULLABLE"),
            ("aggregate_row_count", "INTEGER", "NULLABLE"),
            ("valuation_row_count", "INTEGER", "NULLABLE"),
            ("detail_request_count", "INTEGER", "NULLABLE"),
            ("listing_row_count", "INTEGER", "NULLABLE"),
            ("archived_at", "TIMESTAMP", "REQUIRED"),
        ),
        "partition": "collected_at",
        "cluster": ("scope", "market_snapshot_id"),
    },
    "market_aggregates": {
        "schema": (
            ("market_snapshot_id", "STRING", "REQUIRED"),
            ("scope", "STRING", "REQUIRED"),
            ("collected_at", "TIMESTAMP", "REQUIRED"),
            ("item_id", "INTEGER", "REQUIRED"),
            ("quality", "STRING", "REQUIRED"),
            ("scope_level", "STRING", "REQUIRED"),
            ("min_listing_price", "FLOAT", "NULLABLE"),
            ("min_listing_world_id", "INTEGER", "NULLABLE"),
            ("median_listing_price", "FLOAT", "NULLABLE"),
            ("recent_purchase_price", "FLOAT", "NULLABLE"),
            ("recent_purchase_at", "TIMESTAMP", "NULLABLE"),
            ("recent_purchase_world_id", "INTEGER", "NULLABLE"),
            ("average_sale_price", "FLOAT", "NULLABLE"),
            ("daily_sale_velocity", "FLOAT", "NULLABLE"),
            ("latest_upload_at", "TIMESTAMP", "NULLABLE"),
        ),
        "partition": "collected_at",
        "cluster": ("scope", "item_id", "quality", "scope_level"),
    },
    "currency_valuations": {
        "schema": (
            ("valuation_run_id", "STRING", "REQUIRED"),
            ("market_snapshot_id", "STRING", "REQUIRED"),
            ("static_snapshot_id", "STRING", "REQUIRED"),
            ("scope", "STRING", "REQUIRED"),
            ("collected_at", "TIMESTAMP", "REQUIRED"),
            ("valued_at", "TIMESTAMP", "REQUIRED"),
            ("shop_id", "INTEGER", "REQUIRED"),
            ("offer_index", "INTEGER", "REQUIRED"),
            ("currency_item_id", "INTEGER", "REQUIRED"),
            ("currency_name", "STRING", "NULLABLE"),
            ("currency_quantity", "INTEGER", "REQUIRED"),
            ("reward_item_id", "INTEGER", "REQUIRED"),
            ("reward_name", "STRING", "NULLABLE"),
            ("reward_quantity", "INTEGER", "REQUIRED"),
            ("reward_is_hq", "BOOLEAN", "REQUIRED"),
            ("price_basis", "STRING", "REQUIRED"),
            ("market_unit_price", "FLOAT", "NULLABLE"),
            ("gross_total_gil", "FLOAT", "NULLABLE"),
            ("fee_rate", "FLOAT", "REQUIRED"),
            ("market_fee_gil", "FLOAT", "NULLABLE"),
            ("net_total_gil", "FLOAT", "NULLABLE"),
            ("gross_gil_per_currency", "FLOAT", "NULLABLE"),
            ("net_gil_per_currency", "FLOAT", "NULLABLE"),
            ("daily_sale_velocity", "FLOAT", "NULLABLE"),
            ("latest_upload_at", "TIMESTAMP", "NULLABLE"),
            ("valuation_status", "STRING", "REQUIRED"),
        ),
        "partition": "collected_at",
        "cluster": ("scope", "reward_item_id", "currency_item_id", "valuation_status"),
    },
    "market_failures": {
        "schema": (
            ("market_snapshot_id", "STRING", "REQUIRED"),
            ("scope", "STRING", "REQUIRED"),
            ("collected_at", "TIMESTAMP", "REQUIRED"),
            ("item_id", "INTEGER", "REQUIRED"),
        ),
        "partition": "collected_at",
        "cluster": ("scope", "item_id"),
    },
    "detailed_runs": {
        "schema": (
            ("detail_snapshot_id", "STRING", "REQUIRED"),
            ("market_snapshot_id", "STRING", "REQUIRED"),
            ("scope", "STRING", "REQUIRED"),
            ("collected_at", "TIMESTAMP", "REQUIRED"),
            ("requested_item_count", "INTEGER", "REQUIRED"),
            ("request_count", "INTEGER", "REQUIRED"),
            ("batch_count", "INTEGER", "REQUIRED"),
            ("listing_count", "INTEGER", "REQUIRED"),
            ("payload_sha256", "STRING", "REQUIRED"),
        ),
        "partition": "collected_at",
        "cluster": ("scope", "market_snapshot_id", "detail_snapshot_id"),
    },
    "market_listings": {
        "schema": (
            ("detail_snapshot_id", "STRING", "REQUIRED"),
            ("market_snapshot_id", "STRING", "REQUIRED"),
            ("scope", "STRING", "REQUIRED"),
            ("collected_at", "TIMESTAMP", "REQUIRED"),
            ("item_id", "INTEGER", "REQUIRED"),
            ("world_id", "INTEGER", "REQUIRED"),
            ("quality", "STRING", "REQUIRED"),
            ("listing_rank", "INTEGER", "REQUIRED"),
            ("listing_id", "STRING", "NULLABLE"),
            ("price_per_unit", "INTEGER", "REQUIRED"),
            ("quantity", "INTEGER", "REQUIRED"),
            ("last_review_at", "TIMESTAMP", "NULLABLE"),
        ),
        "partition": "collected_at",
        "cluster": ("scope", "item_id", "world_id", "quality"),
    },
    "signal_observations": {
        "schema": (
            ("signal_key", "STRING", "REQUIRED"),
            ("market_snapshot_id", "STRING", "REQUIRED"),
            ("module", "STRING", "REQUIRED"),
            ("scope", "STRING", "REQUIRED"),
            ("observed_at", "TIMESTAMP", "REQUIRED"),
            ("item_id", "INTEGER", "NULLABLE"),
            ("quality", "STRING", "NULLABLE"),
            ("title", "STRING", "REQUIRED"),
            ("subtitle", "STRING", "NULLABLE"),
            ("state", "STRING", "REQUIRED"),
            ("score", "FLOAT", "REQUIRED"),
            ("metric_name", "STRING", "REQUIRED"),
            ("metric_value", "FLOAT", "REQUIRED"),
            ("reference_value", "FLOAT", "NULLABLE"),
            ("direction", "STRING", "REQUIRED"),
            ("url", "STRING", "REQUIRED"),
            ("reason", "STRING", "REQUIRED"),
            ("payload_json", "STRING", "REQUIRED"),
        ),
        "partition": "observed_at",
        "cluster": ("module", "signal_key", "scope"),
    },
    "static_snapshots": {
        "schema": (
            ("static_snapshot_id", "STRING", "REQUIRED"),
            ("source", "STRING", "REQUIRED"),
            ("game_version", "STRING", "REQUIRED"),
            ("schema_version", "INTEGER", "REQUIRED"),
            ("extracted_at", "TIMESTAMP", "REQUIRED"),
            ("imported_at", "TIMESTAMP", "REQUIRED"),
            ("archived_at", "TIMESTAMP", "REQUIRED"),
        ),
        "partition": "extracted_at",
        "cluster": ("game_version", "static_snapshot_id"),
    },
    "item_catalog": {
        "schema": (
            ("static_snapshot_id", "STRING", "REQUIRED"),
            ("game_version", "STRING", "REQUIRED"),
            ("extracted_at", "TIMESTAMP", "REQUIRED"),
            ("item_id", "INTEGER", "REQUIRED"),
            ("name", "STRING", "NULLABLE"),
            ("icon_id", "INTEGER", "NULLABLE"),
            ("marketable_candidate", "BOOLEAN", "REQUIRED"),
            ("search_category_id", "INTEGER", "NULLABLE"),
            ("search_category_name", "STRING", "NULLABLE"),
            ("ui_category_id", "INTEGER", "NULLABLE"),
            ("ui_category_name", "STRING", "NULLABLE"),
            ("craftable", "BOOLEAN", "NULLABLE"),
            ("craft_type_name", "STRING", "NULLABLE"),
            ("gatherable", "BOOLEAN", "NULLABLE"),
            ("gathering_type", "STRING", "NULLABLE"),
        ),
        "partition": "extracted_at",
        "cluster": ("item_id", "search_category_id", "game_version"),
    },
    "recipes": {
        "schema": (
            ("static_snapshot_id", "STRING", "REQUIRED"),
            ("game_version", "STRING", "REQUIRED"),
            ("extracted_at", "TIMESTAMP", "REQUIRED"),
            ("recipe_id", "INTEGER", "REQUIRED"),
            ("result_item_id", "INTEGER", "REQUIRED"),
            ("result_quantity", "INTEGER", "REQUIRED"),
            ("craft_type_name", "STRING", "REQUIRED"),
            ("recipe_level_table_id", "INTEGER", "NULLABLE"),
            ("patch_number", "INTEGER", "NULLABLE"),
            ("can_hq", "BOOLEAN", "REQUIRED"),
            ("is_expert", "BOOLEAN", "REQUIRED"),
        ),
        "partition": "extracted_at",
        "cluster": ("result_item_id", "craft_type_name", "game_version"),
    },
    "recipe_ingredients": {
        "schema": (
            ("static_snapshot_id", "STRING", "REQUIRED"),
            ("game_version", "STRING", "REQUIRED"),
            ("extracted_at", "TIMESTAMP", "REQUIRED"),
            ("recipe_id", "INTEGER", "REQUIRED"),
            ("ingredient_index", "INTEGER", "REQUIRED"),
            ("item_id", "INTEGER", "REQUIRED"),
            ("quantity", "INTEGER", "REQUIRED"),
        ),
        "partition": "extracted_at",
        "cluster": ("item_id", "recipe_id", "game_version"),
    },
}


@dataclass(frozen=True, slots=True)
class BigQueryArchiveSummary:
    archived_market_snapshots: int
    skipped_market_snapshots: int
    archived_static_snapshots: int
    aggregate_rows: int
    valuation_rows: int
    failure_rows: int
    catalog_rows: int
    recipe_rows: int
    recipe_ingredient_rows: int
    detailed_runs: int
    listing_rows: int
    signal_rows: int


class BigQueryArchive:
    def __init__(
        self,
        *,
        project_id: str,
        dataset_id: str,
        location: str = "US",
        client: Any | None = None,
    ) -> None:
        if not _IDENTIFIER.fullmatch(dataset_id):
            raise ValueError("BigQuery dataset ID contains unsupported characters")
        from google.cloud import bigquery

        self._bigquery = bigquery
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.location = location
        self.client = client or bigquery.Client(project=project_id, location=location)

    def ensure_schema(self) -> None:
        bigquery = self._bigquery
        dataset_ref = bigquery.Dataset(f"{self.project_id}.{self.dataset_id}")
        dataset_ref.location = self.location
        self.client.create_dataset(dataset_ref, exists_ok=True)
        for table_name, spec in TABLES.items():
            table = bigquery.Table(
                self._table_id(table_name),
                schema=[bigquery.SchemaField(*field) for field in spec["schema"]],
            )
            table.time_partitioning = bigquery.TimePartitioning(field=spec["partition"])
            table.clustering_fields = list(spec["cluster"])
            self.client.create_table(table, exists_ok=True)
            current = self.client.get_table(self._table_id(table_name))
            existing_fields = {field.name for field in current.schema}
            missing_fields = [
                bigquery.SchemaField(*field)
                for field in spec["schema"]
                if field[0] not in existing_fields
            ]
            if missing_fields:
                current.schema = [*current.schema, *missing_fields]
                self.client.update_table(current, ["schema"])

    def archive_all(
        self,
        database_path: Path | str,
        *,
        scope: str,
        work_dir: Path,
    ) -> BigQueryArchiveSummary:
        self.ensure_schema()
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        try:
            snapshot_ids = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT market_snapshot_id
                    FROM market_source_snapshot
                    WHERE lower(scope) = lower(?)
                    ORDER BY collected_at, market_snapshot_id
                    """,
                    (scope,),
                )
            ]
            totals = {
                "archived_market_snapshots": 0,
                "skipped_market_snapshots": 0,
                "archived_static_snapshots": 0,
                "aggregate_rows": 0,
                "valuation_rows": 0,
                "failure_rows": 0,
                "catalog_rows": 0,
                "recipe_rows": 0,
                "recipe_ingredient_rows": 0,
                "detailed_runs": 0,
                "listing_rows": 0,
                "signal_rows": 0,
            }
            archived_at = datetime.now(timezone.utc).isoformat()
            static_snapshot_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT snapshot_id FROM source_snapshot ORDER BY extracted_at, snapshot_id"
                )
            ]
            for static_snapshot_id in static_snapshot_ids:
                static_rows = self._archive_static_snapshot(
                    connection,
                    static_snapshot_id,
                    work_dir,
                    archived_at,
                )
                if static_rows is not None:
                    totals["archived_static_snapshots"] += 1
                    for name, count in static_rows.items():
                        totals[name] += count
            for snapshot_id in snapshot_ids:
                summary = self._archive_snapshot(connection, snapshot_id, work_dir)
                for name in totals:
                    totals[name] += summary[name]
        finally:
            connection.close()
        return BigQueryArchiveSummary(**totals)

    def _archive_snapshot(
        self,
        connection: sqlite3.Connection,
        market_snapshot_id: str,
        work_dir: Path,
    ) -> dict[str, int]:
        empty = {
            "archived_market_snapshots": 0,
            "skipped_market_snapshots": 0,
            "archived_static_snapshots": 0,
            "aggregate_rows": 0,
            "valuation_rows": 0,
            "failure_rows": 0,
            "catalog_rows": 0,
            "recipe_rows": 0,
            "recipe_ingredient_rows": 0,
            "detailed_runs": 0,
            "listing_rows": 0,
            "signal_rows": 0,
        }
        if self._marker_exists("market_runs", "market_snapshot_id", market_snapshot_id):
            empty["skipped_market_snapshots"] = 1
            return empty

        market = connection.execute(
            "SELECT * FROM market_source_snapshot WHERE market_snapshot_id = ?",
            (market_snapshot_id,),
        ).fetchone()
        if market is None:
            raise ValueError(f"Unknown market snapshot: {market_snapshot_id}")
        valuation_run = connection.execute(
            """
            SELECT * FROM currency_valuation_run
            WHERE market_snapshot_id = ?
            ORDER BY valued_at DESC, valuation_run_id DESC
            LIMIT 1
            """,
            (market_snapshot_id,),
        ).fetchone()
        archived_at = datetime.now(timezone.utc).isoformat()
        if valuation_run is not None:
            static_rows = self._archive_static_snapshot(
                connection,
                valuation_run["static_snapshot_id"],
                work_dir,
                archived_at,
            )
            if static_rows is not None:
                empty["archived_static_snapshots"] += 1
                for name, count in static_rows.items():
                    empty[name] += count

        aggregate_rows = self._load_rows(
            "market_aggregates",
            _market_aggregate_rows(connection, market_snapshot_id),
            job_key=market_snapshot_id,
            work_dir=work_dir,
        )
        failure_rows = self._load_rows(
            "market_failures",
            _failure_rows(connection, market_snapshot_id),
            job_key=market_snapshot_id,
            work_dir=work_dir,
        )
        valuation_rows = self._load_rows(
            "currency_valuations",
            _valuation_rows(connection, market_snapshot_id),
            job_key=market_snapshot_id,
            work_dir=work_dir,
        )
        listing_rows = self._load_rows(
            "market_listings",
            _listing_rows(connection, market_snapshot_id),
            job_key=market_snapshot_id,
            work_dir=work_dir,
        )
        detail_run_rows = self._load_rows(
            "detailed_runs",
            _detail_run_rows(connection, market_snapshot_id, listing_rows),
            job_key=market_snapshot_id,
            work_dir=work_dir,
        )
        signal_rows = self._load_rows(
            "signal_observations",
            _signal_observation_rows(connection, market_snapshot_id),
            job_key=market_snapshot_id,
            work_dir=work_dir,
        )
        detail = _detail_snapshot(connection, market_snapshot_id)
        run_row = {
            "market_snapshot_id": market_snapshot_id,
            "scope": market["scope"],
            "collected_at": market["collected_at"],
            "source_url": market["source_url"],
            "requested_item_count": market["requested_item_count"],
            "result_item_count": market["result_item_count"],
            "failed_item_count": market["failed_item_count"],
            "request_count": market["request_count"],
            "collection_elapsed_seconds": market["collection_elapsed_seconds"],
            "payload_sha256": market["payload_sha256"],
            "valuation_run_id": valuation_run["valuation_run_id"] if valuation_run else None,
            "static_snapshot_id": valuation_run["static_snapshot_id"] if valuation_run else None,
            "valued_at": valuation_run["valued_at"] if valuation_run else None,
            "market_scope_level": valuation_run["market_scope_level"] if valuation_run else None,
            "price_basis": valuation_run["price_basis"] if valuation_run else None,
            "fee_rate": valuation_run["fee_rate"] if valuation_run else None,
            "freshness_hours": valuation_run["freshness_hours"] if valuation_run else None,
            "aggregate_row_count": aggregate_rows,
            "valuation_row_count": valuation_rows,
            "detail_request_count": detail["request_count"] if detail else None,
            "listing_row_count": listing_rows,
            "archived_at": archived_at,
        }
        self._load_rows(
            "market_runs",
            iter((run_row,)),
            job_key=market_snapshot_id,
            work_dir=work_dir,
        )
        empty.update(
            archived_market_snapshots=1,
            aggregate_rows=aggregate_rows,
            valuation_rows=valuation_rows,
            failure_rows=failure_rows,
            detailed_runs=detail_run_rows,
            listing_rows=listing_rows,
            signal_rows=signal_rows,
        )
        return empty

    def _archive_static_snapshot(
        self,
        connection: sqlite3.Connection,
        static_snapshot_id: str,
        work_dir: Path,
        archived_at: str,
    ) -> dict[str, int] | None:
        if self._marker_exists("static_snapshots", "static_snapshot_id", static_snapshot_id):
            return None
        source = connection.execute(
            "SELECT * FROM source_snapshot WHERE snapshot_id = ?",
            (static_snapshot_id,),
        ).fetchone()
        if source is None:
            raise ValueError(f"Unknown static snapshot: {static_snapshot_id}")
        catalog_rows = self._load_rows(
            "item_catalog",
            _catalog_rows(connection, static_snapshot_id),
            job_key=static_snapshot_id,
            work_dir=work_dir,
        )
        recipe_rows = self._load_rows(
            "recipes",
            _recipe_rows(connection, static_snapshot_id),
            job_key=static_snapshot_id,
            work_dir=work_dir,
        )
        recipe_ingredient_rows = self._load_rows(
            "recipe_ingredients",
            _recipe_ingredient_rows(connection, static_snapshot_id),
            job_key=static_snapshot_id,
            work_dir=work_dir,
        )
        self._load_rows(
            "static_snapshots",
            iter(
                (
                    {
                        "static_snapshot_id": static_snapshot_id,
                        "source": source["source"],
                        "game_version": source["game_version"],
                        "schema_version": source["schema_version"],
                        "extracted_at": source["extracted_at"],
                        "imported_at": source["imported_at"],
                        "archived_at": archived_at,
                    },
                )
            ),
            job_key=static_snapshot_id,
            work_dir=work_dir,
        )
        return {
            "catalog_rows": catalog_rows,
            "recipe_rows": recipe_rows,
            "recipe_ingredient_rows": recipe_ingredient_rows,
        }

    def _marker_exists(self, table: str, field: str, value: str) -> bool:
        bigquery = self._bigquery
        query = f"SELECT 1 FROM `{self._table_id(table)}` WHERE {field} = @value LIMIT 1"
        config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("value", "STRING", value)],
            use_query_cache=True,
        )
        return next(iter(self.client.query(query, job_config=config).result()), None) is not None

    def _load_rows(
        self,
        table: str,
        rows: Iterable[dict[str, Any]],
        *,
        job_key: str,
        work_dir: Path,
    ) -> int:
        work_dir.mkdir(parents=True, exist_ok=True)
        path = work_dir / f"bigquery-{table}.ndjson"
        count = 0
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                stream.write("\n")
                count += 1
        if count == 0:
            path.unlink(missing_ok=True)
            return 0
        bigquery = self._bigquery
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        job_id = _job_id(table, job_key)
        with path.open("rb") as stream:
            try:
                job = self.client.load_table_from_file(
                    stream,
                    self._table_id(table),
                    job_id=job_id,
                    location=self.location,
                    job_config=config,
                )
            except Exception as exc:
                if type(exc).__name__ != "Conflict":
                    raise
                job = self.client.get_job(job_id, location=self.location)
            job.result()
        path.unlink(missing_ok=True)
        return count

    def _table_id(self, table: str) -> str:
        if table not in TABLES:
            raise ValueError(f"Unknown BigQuery table: {table}")
        return f"{self.project_id}.{self.dataset_id}.{table}"


def _market_aggregate_rows(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT market.market_snapshot_id, market.scope, market.collected_at,
               aggregate.item_id, aggregate.quality, aggregate.scope_level,
               aggregate.min_listing_price, aggregate.min_listing_world_id,
               aggregate.median_listing_price, aggregate.recent_purchase_price,
               aggregate.recent_purchase_at, aggregate.recent_purchase_world_id,
               aggregate.average_sale_price, aggregate.daily_sale_velocity,
               (
                   SELECT MAX(freshness.uploaded_at)
                   FROM fact_data_freshness AS freshness
                   WHERE freshness.market_snapshot_id = aggregate.market_snapshot_id
                     AND freshness.item_id = aggregate.item_id
               ) AS latest_upload_at
        FROM fact_market_aggregate_snapshot AS aggregate
        JOIN market_source_snapshot AS market USING (market_snapshot_id)
        WHERE aggregate.market_snapshot_id = ?
        ORDER BY aggregate.item_id, aggregate.quality, aggregate.scope_level
        """,
        (market_snapshot_id,),
    )
    for row in rows:
        yield dict(row)


def _failure_rows(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT failure.market_snapshot_id, market.scope, market.collected_at, failure.item_id
        FROM market_snapshot_failure AS failure
        JOIN market_source_snapshot AS market USING (market_snapshot_id)
        WHERE failure.market_snapshot_id = ?
        ORDER BY failure.item_id
        """,
        (market_snapshot_id,),
    )
    for row in rows:
        yield dict(row)


def _valuation_rows(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT value.valuation_run_id, value.market_snapshot_id, value.static_snapshot_id,
               run.scope, market.collected_at, run.valued_at,
               value.shop_id, value.offer_index, value.currency_item_id,
               value.currency_name, value.currency_quantity, value.reward_item_id,
               value.reward_name, value.reward_quantity, value.reward_is_hq,
               value.price_basis, value.market_unit_price, value.gross_total_gil,
               value.fee_rate, value.market_fee_gil, value.net_total_gil,
               value.gross_gil_per_currency, value.net_gil_per_currency,
               value.daily_sale_velocity, value.latest_upload_at, value.valuation_status
        FROM currency_market_valuation AS value
        JOIN currency_valuation_run AS run USING (valuation_run_id)
        JOIN market_source_snapshot AS market USING (market_snapshot_id)
        WHERE value.market_snapshot_id = ?
          AND value.valuation_status IN ('FRESH', 'STALE')
        ORDER BY value.valuation_run_id, value.shop_id, value.offer_index
        """,
        (market_snapshot_id,),
    )
    for row in rows:
        payload = dict(row)
        payload["reward_is_hq"] = bool(payload["reward_is_hq"])
        yield payload


def _detail_snapshot(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
) -> sqlite3.Row | None:
    if not _sqlite_table_exists(connection, "detail_source_snapshot"):
        return None
    return connection.execute(
        "SELECT * FROM detail_source_snapshot WHERE market_snapshot_id = ?",
        (market_snapshot_id,),
    ).fetchone()


def _detail_run_rows(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
    listing_count: int,
) -> Iterator[dict[str, Any]]:
    detail = _detail_snapshot(connection, market_snapshot_id)
    if detail is None:
        return
    market = connection.execute(
        "SELECT scope FROM market_source_snapshot WHERE market_snapshot_id = ?",
        (market_snapshot_id,),
    ).fetchone()
    yield {
        "detail_snapshot_id": detail["detail_snapshot_id"],
        "market_snapshot_id": market_snapshot_id,
        "scope": market["scope"],
        "collected_at": detail["collected_at"],
        "requested_item_count": detail["requested_item_count"],
        "request_count": detail["request_count"],
        "batch_count": detail["batch_count"],
        "listing_count": listing_count,
        "payload_sha256": detail["payload_sha256"],
    }


def _listing_rows(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    if not _sqlite_table_exists(connection, "fact_market_listing_snapshot"):
        return
    rows = connection.execute(
        """
        SELECT detail.detail_snapshot_id, detail.market_snapshot_id,
               market.scope, detail.collected_at, listing.item_id,
               listing.world_id, listing.quality, listing.listing_rank,
               listing.listing_id, listing.price_per_unit, listing.quantity,
               listing.last_review_at
        FROM fact_market_listing_snapshot AS listing
        JOIN detail_source_snapshot AS detail USING (detail_snapshot_id)
        JOIN market_source_snapshot AS market USING (market_snapshot_id)
        WHERE detail.market_snapshot_id = ?
        ORDER BY listing.item_id, listing.world_id,
                 listing.quality, listing.listing_rank
        """,
        (market_snapshot_id,),
    )
    for row in rows:
        yield dict(row)


def _signal_observation_rows(
    connection: sqlite3.Connection,
    market_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    if not _sqlite_table_exists(connection, "fact_signal_observation"):
        return
    rows = connection.execute(
        """
        SELECT signal_key, market_snapshot_id, module, scope, observed_at,
               item_id, quality, title, subtitle, state, score, metric_name,
               metric_value, reference_value, direction, url, reason, payload_json
        FROM fact_signal_observation
        WHERE market_snapshot_id = ?
        ORDER BY module, signal_key
        """,
        (market_snapshot_id,),
    )
    for row in rows:
        yield dict(row)


def _catalog_rows(
    connection: sqlite3.Connection,
    static_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(dim_asset)")}
    optional = {
        name: name if name in columns else f"NULL AS {name}"
        for name in (
            "icon_id",
            "search_category_id",
            "search_category_name",
            "ui_category_id",
            "ui_category_name",
            "craftable",
            "craft_type_name",
            "gatherable",
            "gathering_type",
        )
    }
    rows = connection.execute(
        f"""
        SELECT asset.snapshot_id AS static_snapshot_id, source.game_version,
               source.extracted_at, asset.item_id, asset.name,
               {optional['icon_id']},
               asset.marketable_candidate,
               {optional['search_category_id']}, {optional['search_category_name']},
               {optional['ui_category_id']}, {optional['ui_category_name']},
               {optional['craftable']}, {optional['craft_type_name']},
               {optional['gatherable']}, {optional['gathering_type']}
        FROM dim_asset AS asset
        JOIN source_snapshot AS source ON source.snapshot_id = asset.snapshot_id
        WHERE asset.snapshot_id = ?
        ORDER BY asset.item_id
        """,
        (static_snapshot_id,),
    )
    for row in rows:
        payload = dict(row)
        payload["marketable_candidate"] = bool(payload["marketable_candidate"])
        if payload["craftable"] is not None:
            payload["craftable"] = bool(payload["craftable"])
        if payload["gatherable"] is not None:
            payload["gatherable"] = bool(payload["gatherable"])
        yield payload


def _recipe_rows(
    connection: sqlite3.Connection,
    static_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    if not _sqlite_table_exists(connection, "dim_recipe"):
        return
    rows = connection.execute(
        """
        SELECT recipe.snapshot_id AS static_snapshot_id, source.game_version,
               source.extracted_at, recipe.recipe_id, recipe.result_item_id,
               recipe.result_quantity, recipe.craft_type_name,
               recipe.recipe_level_table_id, recipe.patch_number,
               recipe.can_hq, recipe.is_expert
        FROM dim_recipe AS recipe
        JOIN source_snapshot AS source ON source.snapshot_id = recipe.snapshot_id
        WHERE recipe.snapshot_id = ?
        ORDER BY recipe.recipe_id
        """,
        (static_snapshot_id,),
    )
    for row in rows:
        payload = dict(row)
        payload["can_hq"] = bool(payload["can_hq"])
        payload["is_expert"] = bool(payload["is_expert"])
        yield payload


def _recipe_ingredient_rows(
    connection: sqlite3.Connection,
    static_snapshot_id: str,
) -> Iterator[dict[str, Any]]:
    if not _sqlite_table_exists(connection, "bridge_recipe_ingredient"):
        return
    rows = connection.execute(
        """
        SELECT ingredient.snapshot_id AS static_snapshot_id, source.game_version,
               source.extracted_at, ingredient.recipe_id,
               ingredient.ingredient_index, ingredient.item_id, ingredient.quantity
        FROM bridge_recipe_ingredient AS ingredient
        JOIN source_snapshot AS source ON source.snapshot_id = ingredient.snapshot_id
        WHERE ingredient.snapshot_id = ?
        ORDER BY ingredient.recipe_id, ingredient.ingredient_index
        """,
        (static_snapshot_id,),
    )
    for row in rows:
        yield dict(row)


def _sqlite_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _job_id(table: str, key: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    return f"cactuar_{table}_{normalized}"[:1024]
