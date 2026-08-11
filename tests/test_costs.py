from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from gil_intelligence.cloud.costs import CloudCostService


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def result(self):
        return self.rows


class _Client:
    def __init__(self, tables=(), rows=()):
        self.tables = tables
        self.rows = rows
        self.query_text = None
        self.job_config = None

    def list_tables(self, dataset):
        assert dataset == "project.billing_export"
        return [SimpleNamespace(table_id=table) for table in self.tables]

    def query(self, query, *, job_config, location):
        self.query_text = query
        self.job_config = job_config
        assert location == "US"
        return _Query(self.rows)


class _BigQuery:
    class QueryJobConfig:
        def __init__(self, *, query_parameters):
            self.query_parameters = query_parameters

    class ScalarQueryParameter:
        def __init__(self, name, kind, value):
            self.name = name
            self.kind = kind
            self.value = value


def test_cost_service_reports_pending_until_export_exists():
    service = CloudCostService(
        project_id="project", client=_Client(), bigquery_module=_BigQuery
    )

    result = service.month_to_date()

    assert result["status"] == "PENDING_EXPORT"
    assert result["reason"] == "EXPORT_NOT_ENABLED"
    assert result["dataset"] == "project.billing_export"


def test_cost_service_sums_project_month_to_date_export():
    client = _Client(
        tables=("unrelated", "gcp_billing_export_v1_01A853_7E501A_C04A83"),
        rows=(
            {
                "service": "Cloud Run",
                "currency": "CLP",
                "gross_cost": 120.0,
                "credits": -100.0,
                "net_cost": 20.0,
                "latest_export_at": datetime(2026, 8, 11, tzinfo=timezone.utc),
            },
            {
                "service": "Artifact Registry",
                "currency": "CLP",
                "gross_cost": 15.0,
                "credits": 0.0,
                "net_cost": 15.0,
                "latest_export_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
            },
        ),
    )
    service = CloudCostService(
        project_id="project", client=client, bigquery_module=_BigQuery
    )

    result = service.month_to_date()

    assert result["status"] == "READY"
    assert result["currency"] == "CLP"
    assert result["grossCost"] == 135
    assert result["credits"] == -100
    assert result["netCost"] == 35
    assert result["latestExportAt"] == "2026-08-11T00:00:00+00:00"
    assert "project.id = @project_id" in client.query_text
    assert client.job_config.query_parameters[0].value == "project"
