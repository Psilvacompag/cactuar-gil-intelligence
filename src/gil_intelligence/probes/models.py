from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ProbeStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


@dataclass(slots=True)
class JsonResponse:
    url: str
    status: int
    headers: dict[str, str]
    data: Any
    elapsed_ms: int


@dataclass(slots=True)
class EndpointProbe:
    name: str
    url: str
    status: ProbeStatus
    elapsed_ms: int | None = None
    http_status: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class SourceProbe:
    source: str
    status: ProbeStatus
    endpoints: list[EndpointProbe]
    findings: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FeasibilityReport:
    generated_at: str
    scope: str
    sources: list[SourceProbe]
    request_budget: dict[str, Any]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

