from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StoredObject:
    content: bytes
    generation: str
    updated_at: str | None


class GcsObjectStore:
    """Small, lazy wrapper so local unit tests do not require Google credentials."""

    def __init__(self, bucket_name: str, *, client: Any | None = None) -> None:
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self._client = client
        self._bucket = client.bucket(bucket_name)

    def download_if_exists(self, object_name: str, destination: Path) -> bool:
        blob = self._bucket.blob(object_name)
        if not blob.exists(client=self._client):
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(destination))
        return True

    def download(self, object_name: str) -> StoredObject:
        blob = self._bucket.blob(object_name)
        blob.reload(client=self._client)
        generation = str(blob.generation)
        content = blob.download_as_bytes(if_generation_match=int(generation))
        updated_at = blob.updated.isoformat() if blob.updated is not None else None
        return StoredObject(content=content, generation=generation, updated_at=updated_at)

    def upload_file(
        self,
        source: Path,
        object_name: str,
        *,
        content_type: str,
        cache_control: str,
    ) -> None:
        blob = self._bucket.blob(object_name)
        blob.cache_control = cache_control
        blob.upload_from_filename(str(source), content_type=content_type)

    def upload_bytes(
        self,
        content: bytes,
        object_name: str,
        *,
        content_type: str,
        cache_control: str,
    ) -> None:
        blob = self._bucket.blob(object_name)
        blob.cache_control = cache_control
        blob.upload_from_string(content, content_type=content_type)
