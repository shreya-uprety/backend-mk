"""Storage abstraction layer with GCS and local filesystem backends.

Usage:
    from storage import get_storage
    storage = get_storage()
    storage.write_json("pipeline_output/p0001/record.json", data)
    data = storage.read_json("pipeline_output/p0001/record.json")
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from dotenv import load_dotenv

# Load .env so GCS_BUCKET_NAME is available regardless of import order
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class StorageBackend(ABC):
    """Abstract interface for file storage operations."""

    @abstractmethod
    def read_json(self, path: str) -> dict:
        """Read and parse a JSON file."""

    @abstractmethod
    def write_json(self, path: str, data: dict) -> None:
        """Write a dict as JSON."""

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Read raw bytes from a file."""

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None:
        """Write raw bytes to a file."""

    @abstractmethod
    def list_blobs(self, prefix: str) -> list[str]:
        """List all blob paths under a prefix."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a file/blob exists."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete a file/blob."""


class LocalBackend(StorageBackend):
    """Local filesystem storage — for development."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def _resolve(self, path: str) -> Path:
        return self.base_dir / path

    def read_json(self, path: str) -> dict:
        with open(self._resolve(path), encoding="utf-8") as f:
            return json.load(f)

    def write_json(self, path: str, data: dict) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def read_bytes(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def write_bytes(self, path: str, data: bytes) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    def list_blobs(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if not base.exists():
            return []
        results = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                results.append(str(p.relative_to(self.base_dir)).replace("\\", "/"))
        return results

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def delete(self, path: str) -> None:
        full = self._resolve(path)
        if full.exists():
            full.unlink()


class GCSBackend(StorageBackend):
    """Google Cloud Storage backend — for production."""

    def __init__(self, bucket_name: str):
        from google.cloud import storage as gcs_lib
        project = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "medforce-milton-key-pilot-dev"))
        self._client = gcs_lib.Client(project=project)
        self._bucket = self._client.bucket(bucket_name)

    def read_json(self, path: str) -> dict:
        blob = self._bucket.blob(path)
        return json.loads(blob.download_as_text())

    def write_json(self, path: str, data: dict) -> None:
        blob = self._bucket.blob(path)
        blob.upload_from_string(
            json.dumps(data, indent=2),
            content_type="application/json",
        )

    def read_bytes(self, path: str) -> bytes:
        blob = self._bucket.blob(path)
        return blob.download_as_bytes()

    def write_bytes(self, path: str, data: bytes) -> None:
        blob = self._bucket.blob(path)
        blob.upload_from_string(data)

    def list_blobs(self, prefix: str) -> list[str]:
        # Ensure prefix ends with / for directory-like listing
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return [blob.name for blob in self._bucket.list_blobs(prefix=prefix)]

    def exists(self, path: str) -> bool:
        return self._bucket.blob(path).exists()

    def delete(self, path: str) -> None:
        blob = self._bucket.blob(path)
        if blob.exists():
            blob.delete()


# ── Singleton ──────────────────────────────────────────────────────────

_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured storage backend (cached singleton).

    Uses GCSBackend if GCS_BUCKET_NAME env var is set, else LocalBackend.
    """
    global _storage
    if _storage is not None:
        return _storage

    bucket_name = os.getenv("GCS_BUCKET_NAME", "")
    if bucket_name:
        _storage = GCSBackend(bucket_name)
    else:
        # Default local data directory
        base_dir = Path(__file__).resolve().parent.parent / "data"
        base_dir.mkdir(parents=True, exist_ok=True)
        _storage = LocalBackend(base_dir)

    return _storage
