from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import JsonResponse


class ProbeNetworkError(RuntimeError):
    """Raised when a probe cannot obtain a JSON response."""


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0.0, (retry_at - current).total_seconds())


class JsonHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        requests_per_second: float = 2.0,
        timeout_seconds: float = 10.0,
        max_retries: int = 1,
        max_retry_wait_seconds: float = 10.0,
        user_agent: str = "ffxiv-gil-intelligence-feasibility/0.0.1",
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_retry_wait_seconds = max_retry_wait_seconds
        self.user_agent = user_agent
        self._minimum_interval = 1.0 / requests_per_second
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_started: float | None = None
        self.request_attempt_count = 0
        self.successful_request_count = 0

    def get_json(self, path: str, query: dict[str, Any] | None = None) -> JsonResponse:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            filtered = {key: value for key, value in query.items() if value is not None}
            url = f"{url}?{urlencode(filtered)}"

        for attempt in range(self.max_retries + 1):
            self._throttle()
            started = self._monotonic()
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.user_agent,
                },
                method="GET",
            )
            self.request_attempt_count += 1
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                    elapsed_ms = round((self._monotonic() - started) * 1000)
                    data = json.loads(raw.decode("utf-8"))
                    self.successful_request_count += 1
                    return JsonResponse(
                        url=url,
                        status=response.status,
                        headers={key.lower(): value for key, value in response.headers.items()},
                        data=data,
                        elapsed_ms=elapsed_ms,
                    )
            except HTTPError as exc:
                if exc.code == 429 and attempt < self.max_retries:
                    retry_after = parse_retry_after(exc.headers.get("Retry-After"))
                    wait_seconds = min(
                        self.max_retry_wait_seconds,
                        retry_after if retry_after is not None else 2**attempt,
                    )
                    self._sleep(wait_seconds)
                    continue
                raise ProbeNetworkError(f"HTTP {exc.code} for {url}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                if attempt < self.max_retries:
                    self._sleep(min(self.max_retry_wait_seconds, 2**attempt))
                    continue
                raise ProbeNetworkError(f"{type(exc).__name__} for {url}: {exc}") from exc

        raise ProbeNetworkError(f"Retry budget exhausted for {url}")

    def _throttle(self) -> None:
        now = self._monotonic()
        if self._last_request_started is not None:
            remaining = self._minimum_interval - (now - self._last_request_started)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_started = now
