from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

from .budget import estimate_market_request_budget
from .http import JsonHttpClient, ProbeNetworkError
from .models import EndpointProbe, FeasibilityReport, JsonResponse, ProbeStatus, SourceProbe


class JsonClient(Protocol):
    def get_json(self, path: str, query: dict[str, Any] | None = None) -> JsonResponse: ...


SHOP_SHEET_CANDIDATES = (
    "SpecialShop",
    "GCScripShopItem",
    "GCShop",
    "InclusionShop",
    "CollectablesShop",
    "FccShop",
    "DisposalShop",
    "LotteryExchangeShop",
    "TomestoneConvert",
    "GilShop",
)

SHOP_DISCOVERY_TOKENS = (
    "shop",
    "exchange",
    "convert",
    "currency",
    "disposal",
    "lottery",
    "scrip",
    "tomestone",
    "trade",
)

STRUCTURAL_SHEETS = (
    "Item",
    "ENpcBase",
    "ENpcResident",
    "Level",
)


def _endpoint_success(name: str, response: JsonResponse, details: dict[str, Any]) -> EndpointProbe:
    return EndpointProbe(
        name=name,
        url=response.url,
        status=ProbeStatus.PASS,
        elapsed_ms=response.elapsed_ms,
        http_status=response.status,
        details=details,
    )


def _endpoint_failure(name: str, url: str, exc: Exception) -> EndpointProbe:
    message = str(exc)
    blocked = any(token in message.lower() for token in ("forbidden", "permission", "10013"))
    return EndpointProbe(
        name=name,
        url=url,
        status=ProbeStatus.BLOCKED if blocked else ProbeStatus.FAIL,
        error=message,
    )


def probe_xivapi(client: JsonClient) -> SourceProbe:
    endpoints: list[EndpointProbe] = []
    findings: dict[str, Any] = {
        "shop_sheet_candidates": list(SHOP_SHEET_CANDIDATES),
        "present_shop_sheets": [],
        "missing_shop_sheets": [],
        "suspected_shop_sheets": [],
        "unclassified_shop_sheets": [],
        "missing_structural_sheets": [],
        "sampled_shop_shapes": {},
    }

    try:
        versions = client.get_json("/api/version")
        version_rows = versions.data.get("versions", []) if isinstance(versions.data, dict) else []
        if not isinstance(version_rows, list):
            raise ValueError("XIVAPI /api/version did not return a versions list")
        endpoints.append(
            _endpoint_success(
                "xivapi_versions",
                versions,
                {"version_count": len(version_rows), "has_latest": any("latest" in row.get("names", []) for row in version_rows)},
            )
        )
    except (ProbeNetworkError, ValueError) as exc:
        endpoints.append(_endpoint_failure("xivapi_versions", f"{getattr(client, 'base_url', '')}/api/version", exc))

    sheet_names: set[str] | None = None
    try:
        sheets = client.get_json("/api/sheet")
        sheet_rows = sheets.data.get("sheets", []) if isinstance(sheets.data, dict) else []
        if not isinstance(sheet_rows, list):
            raise ValueError("XIVAPI /api/sheet did not return a sheets list")
        sheet_names = {
            row["name"]
            for row in sheet_rows
            if isinstance(row, dict) and isinstance(row.get("name"), str)
        }
        present = [name for name in SHOP_SHEET_CANDIDATES if name in sheet_names]
        missing = [name for name in SHOP_SHEET_CANDIDATES if name not in sheet_names]
        findings["present_shop_sheets"] = present
        findings["missing_shop_sheets"] = missing
        suspected = sorted(
            name
            for name in sheet_names
            if any(token in name.lower() for token in SHOP_DISCOVERY_TOKENS)
        )
        findings["suspected_shop_sheets"] = suspected
        findings["unclassified_shop_sheets"] = [
            name for name in suspected if name not in SHOP_SHEET_CANDIDATES
        ]
        findings["missing_structural_sheets"] = [
            name for name in STRUCTURAL_SHEETS if name not in sheet_names
        ]
        endpoints.append(
            _endpoint_success(
                "xivapi_sheets",
                sheets,
                {
                    "sheet_count": len(sheet_names),
                    "candidate_shop_sheets_present": len(present),
                    "suspected_shop_sheets": len(suspected),
                    "unclassified_shop_sheets": len(findings["unclassified_shop_sheets"]),
                },
            )
        )
    except (ProbeNetworkError, ValueError, KeyError) as exc:
        endpoints.append(_endpoint_failure("xivapi_sheets", f"{getattr(client, 'base_url', '')}/api/sheet", exc))

    if sheet_names is not None:
        for sheet_name in findings["present_shop_sheets"]:
            try:
                sample = client.get_json(
                    f"/api/sheet/{quote(sheet_name)}",
                    {"limit": 1, "version": "latest", "language": "en"},
                )
                rows = sample.data.get("rows", []) if isinstance(sample.data, dict) else []
                if not isinstance(rows, list):
                    raise ValueError(f"{sheet_name} did not return rows")
                first_fields = rows[0].get("fields", {}) if rows else {}
                details = {
                    "sample_row_count": len(rows),
                    "top_level_fields": sorted(first_fields) if isinstance(first_fields, dict) else [],
                    "version": sample.data.get("version") if isinstance(sample.data, dict) else None,
                    "schema": sample.data.get("schema") if isinstance(sample.data, dict) else None,
                }
                findings["sampled_shop_shapes"][sheet_name] = details
                endpoints.append(_endpoint_success(f"xivapi_shop_{sheet_name}", sample, details))
            except (ProbeNetworkError, ValueError) as exc:
                endpoints.append(
                    _endpoint_failure(
                        f"xivapi_shop_{sheet_name}",
                        f"{getattr(client, 'base_url', '')}/api/sheet/{sheet_name}",
                        exc,
                    )
                )

    critical = [item for item in endpoints if item.name in {"xivapi_versions", "xivapi_sheets"}]
    if any(item.status == ProbeStatus.BLOCKED for item in critical):
        status = ProbeStatus.BLOCKED
    elif any(item.status == ProbeStatus.FAIL for item in critical):
        status = ProbeStatus.FAIL
    elif (
        findings["missing_shop_sheets"]
        or findings["unclassified_shop_sheets"]
        or findings["missing_structural_sheets"]
        or any(item.status != ProbeStatus.PASS for item in endpoints)
    ):
        status = ProbeStatus.WARN
    else:
        status = ProbeStatus.PASS
    return SourceProbe(source="XIVAPI", status=status, endpoints=endpoints, findings=findings)


def probe_universalis(client: JsonClient, *, scope: str) -> tuple[SourceProbe, int | None]:
    endpoints: list[EndpointProbe] = []
    findings: dict[str, Any] = {"scope": scope}

    try:
        data_centers = client.get_json("/api/v2/data-centers")
        if not isinstance(data_centers.data, list):
            raise ValueError("Universalis data-centers response was not a list")
        names = [row.get("name") for row in data_centers.data if isinstance(row, dict)]
        findings["scope_found"] = scope in names
        endpoints.append(
            _endpoint_success(
                "universalis_data_centers",
                data_centers,
                {"data_center_count": len(data_centers.data), "scope_found": scope in names},
            )
        )
    except (ProbeNetworkError, ValueError) as exc:
        endpoints.append(
            _endpoint_failure(
                "universalis_data_centers",
                f"{getattr(client, 'base_url', '')}/api/v2/data-centers",
                exc,
            )
        )

    marketable_count: int | None = None
    sample_ids: list[int] = []
    try:
        marketable = client.get_json("/api/v2/marketable")
        if not isinstance(marketable.data, list) or not all(isinstance(item, int) for item in marketable.data):
            raise ValueError("Universalis marketable response was not an integer list")
        marketable_count = len(marketable.data)
        sample_ids = marketable.data[:3]
        findings["marketable_item_count"] = marketable_count
        endpoints.append(
            _endpoint_success(
                "universalis_marketable",
                marketable,
                {"marketable_item_count": marketable_count, "sample_item_ids": sample_ids},
            )
        )
    except (ProbeNetworkError, ValueError) as exc:
        endpoints.append(
            _endpoint_failure(
                "universalis_marketable",
                f"{getattr(client, 'base_url', '')}/api/v2/marketable",
                exc,
            )
        )

    if sample_ids:
        encoded_scope = quote(scope, safe="")
        encoded_ids = ",".join(str(item_id) for item_id in sample_ids)
        try:
            aggregated = client.get_json(f"/api/v2/aggregated/{encoded_scope}/{encoded_ids}")
            results = aggregated.data.get("results", []) if isinstance(aggregated.data, dict) else []
            if not isinstance(results, list):
                raise ValueError("Universalis aggregated response did not contain results")
            endpoints.append(
                _endpoint_success(
                    "universalis_aggregated",
                    aggregated,
                    {"requested_items": len(sample_ids), "result_count": len(results)},
                )
            )
        except (ProbeNetworkError, ValueError) as exc:
            endpoints.append(
                _endpoint_failure(
                    "universalis_aggregated",
                    f"{getattr(client, 'base_url', '')}/api/v2/aggregated/{encoded_scope}/{encoded_ids}",
                    exc,
                )
            )

    critical = [item for item in endpoints if item.name in {"universalis_data_centers", "universalis_marketable"}]
    if any(item.status == ProbeStatus.BLOCKED for item in critical):
        status = ProbeStatus.BLOCKED
    elif any(item.status == ProbeStatus.FAIL for item in critical):
        status = ProbeStatus.FAIL
    elif any(item.status != ProbeStatus.PASS for item in endpoints):
        status = ProbeStatus.WARN
    else:
        status = ProbeStatus.PASS
    return SourceProbe(source="Universalis", status=status, endpoints=endpoints, findings=findings), marketable_count


def build_feasibility_report(
    *,
    scope: str,
    timeout_seconds: float = 10.0,
    requests_per_second: float = 2.0,
    max_retries: int = 1,
) -> FeasibilityReport:
    xivapi_client = JsonHttpClient(
        "https://v2.xivapi.com",
        timeout_seconds=timeout_seconds,
        requests_per_second=requests_per_second,
        max_retries=max_retries,
    )
    universalis_client = JsonHttpClient(
        "https://universalis.app",
        timeout_seconds=timeout_seconds,
        requests_per_second=requests_per_second,
        max_retries=max_retries,
    )
    xivapi = probe_xivapi(xivapi_client)
    universalis, marketable_count = probe_universalis(universalis_client, scope=scope)
    assumed_count = marketable_count if marketable_count is not None else 30_000
    return FeasibilityReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        scope=scope,
        sources=[xivapi, universalis],
        request_budget=estimate_market_request_budget(
            assumed_count,
            safe_requests_per_second=requests_per_second,
        ),
        limitations=[
            "The probe samples one row per discovered shop sheet; it does not claim full shop coverage.",
            "Vendor locations and unlock requirements require cross-sheet reconstruction and a later coverage crawl.",
            "Universalis data is crowd-sourced; freshness must be carried into every valuation.",
            "The request budget assumes Universalis batches of up to 100 item IDs.",
        ],
    )
