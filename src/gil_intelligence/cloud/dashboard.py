from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .gcs import StoredObject


class ObjectReader(Protocol):
    def download(self, object_name: str) -> StoredObject: ...


@dataclass(frozen=True, slots=True)
class DashboardDocument:
    content: bytes
    generation: str
    updated_at: str | None

    @property
    def etag(self) -> str:
        return f'"gcs-{self.generation}"'


class DashboardCache:
    def __init__(
        self,
        store: ObjectReader,
        object_name: str,
        *,
        ttl_seconds: int = 60,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._object_name = object_name
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._expires_at = 0.0
        self._document: DashboardDocument | None = None

    def get(self) -> DashboardDocument:
        now = self._monotonic()
        if self._document is not None and now < self._expires_at:
            return self._document

        stored = self._store.download(self._object_name)
        payload = json.loads(stored.content)
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            raise ValueError("Dashboard object has an unsupported schema")
        document = DashboardDocument(
            content=stored.content,
            generation=stored.generation,
            updated_at=stored.updated_at,
        )
        self._document = document
        self._expires_at = now + self._ttl_seconds
        return document
