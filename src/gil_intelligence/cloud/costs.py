from __future__ import annotations

import re
from typing import Any


_BILLING_TABLE = re.compile(r"^gcp_billing_export_v1_[A-F0-9_]+$")


class CloudCostService:
    """Read month-to-date project costs from the standard Cloud Billing export."""

    def __init__(
        self,
        *,
        project_id: str,
        dataset_id: str = "billing_export",
        location: str = "US",
        client: Any | None = None,
        bigquery_module: Any | None = None,
    ) -> None:
        if bigquery_module is None:
            from google.cloud import bigquery

            bigquery_module = bigquery
        self._bigquery = bigquery_module
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.location = location
        self.client = client or bigquery_module.Client(project=project_id, location=location)

    def month_to_date(self) -> dict[str, Any]:
        dataset = f"{self.project_id}.{self.dataset_id}"
        try:
            tables = list(self.client.list_tables(dataset))
        except Exception as exc:  # Billing export is optional until enabled in Console.
            return self._pending("DATASET_UNAVAILABLE", type(exc).__name__)
        table_ids = sorted(
            table.table_id for table in tables if _BILLING_TABLE.fullmatch(table.table_id)
        )
        if not table_ids:
            return self._pending("EXPORT_NOT_ENABLED")

        table_id = table_ids[-1]
        query = f"""
            SELECT
              service.description AS service,
              currency,
              SUM(cost) AS gross_cost,
              SUM(IFNULL((SELECT SUM(credit.amount) FROM UNNEST(credits) AS credit), 0)) AS credits,
              SUM(cost) + SUM(IFNULL((SELECT SUM(credit.amount) FROM UNNEST(credits) AS credit), 0)) AS net_cost,
              MAX(export_time) AS latest_export_at
            FROM `{dataset}.{table_id}`
            WHERE project.id = @project_id
              AND usage_start_time >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH)
            GROUP BY service, currency
            ORDER BY net_cost DESC
        """
        config = self._bigquery.QueryJobConfig(
            query_parameters=[
                self._bigquery.ScalarQueryParameter("project_id", "STRING", self.project_id)
            ]
        )
        rows = list(self.client.query(query, job_config=config, location=self.location).result())
        services = [
            {
                "service": _value(row, "service"),
                "currency": _value(row, "currency"),
                "grossCost": float(_value(row, "gross_cost") or 0),
                "credits": float(_value(row, "credits") or 0),
                "netCost": float(_value(row, "net_cost") or 0),
                "latestExportAt": _iso(_value(row, "latest_export_at")),
            }
            for row in rows
        ]
        currency = services[0]["currency"] if services else None
        latest = max(
            (entry["latestExportAt"] for entry in services if entry["latestExportAt"]),
            default=None,
        )
        return {
            "status": "READY",
            "projectId": self.project_id,
            "dataset": dataset,
            "table": table_id,
            "period": "MONTH_TO_DATE",
            "currency": currency,
            "grossCost": sum(entry["grossCost"] for entry in services),
            "credits": sum(entry["credits"] for entry in services),
            "netCost": sum(entry["netCost"] for entry in services),
            "latestExportAt": latest,
            "services": services,
        }

    def _pending(self, reason: str, detail: str | None = None) -> dict[str, Any]:
        return {
            "status": "PENDING_EXPORT",
            "reason": reason,
            "detail": detail,
            "projectId": self.project_id,
            "dataset": f"{self.project_id}.{self.dataset_id}",
            "period": "MONTH_TO_DATE",
            "services": [],
        }


def _value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError):
        return getattr(row, key, None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
