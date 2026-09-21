"""Private Blob adapter for the hosted profile, deliberately separate from local GC.

The core still uses PrivateStorage. Enabling hosted storage also requires durable
upload quarantine and a cloud deletion ledger; a working SDK is not that rollout.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import BoundedSemaphore
from typing import TypeVar

from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.core.paging import PageIterator
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient, ContainerClient

MAX_OBJECT_BYTES = 10 * 1024 * 1024
IO_SLOTS = BoundedSemaphore(4)
T = TypeVar("T")


@dataclass(frozen=True)
class BlobEntry:
    key: str
    modified_at: datetime


@dataclass(frozen=True)
class BlobPage:
    entries: tuple[BlobEntry, ...]
    next_cursor: str | None


def validate_blob_key(key: str) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_./-]{1,500}", key) or ".." in key or key.startswith("/"):
        raise ValueError("Chave de objeto inválida")


class AzureBlobStorage:
    """Immutable writes, bounded downloads and idempotent delete; no public URLs/SAS."""

    def __init__(self, container: ContainerClient):
        self.container = container
        self._service: BlobServiceClient | None = None
        self._credential: ManagedIdentityCredential | None = None

    @classmethod
    def managed_identity(
        cls, account_name: str, container_name: str, *, client_id: str | None = None
    ) -> AzureBlobStorage:
        if not re.fullmatch(r"[a-z0-9]{3,24}", account_name):
            raise ValueError("Nome da conta Blob inválido")
        if (
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]", container_name)
            or "--" in container_name
        ):
            raise ValueError("Nome do container privado inválido")
        credential = ManagedIdentityCredential(client_id=client_id)
        service = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=credential,
            connection_timeout=3,
            read_timeout=10,
            retry_total=0,
            max_single_get_size=1024 * 1024,
            max_chunk_get_size=1024 * 1024,
            max_single_put_size=MAX_OBJECT_BYTES,
            logging_enable=False,
        )
        storage = cls(service.get_container_client(container_name))
        storage._service = service
        storage._credential = credential
        return storage

    def close(self) -> None:
        self.container.close()
        if self._service is not None:
            self._service.close()
        if self._credential is not None:
            self._credential.close()

    def _read(self, key: str) -> bytes:
        blob = self.container.get_blob_client(key)
        download = blob.download_blob(max_concurrency=1, timeout=10)
        if download.size > MAX_OBJECT_BYTES:
            raise OSError("Objeto excede o limite privado de armazenamento")
        content = bytearray()
        for chunk in download.chunks():
            if len(content) + len(chunk) > MAX_OBJECT_BYTES:
                raise OSError("Objeto excede o limite privado de armazenamento")
            content.extend(chunk)
        return bytes(content)

    def _execute(self, operation: Callable[[], T]) -> T:
        if not IO_SLOTS.acquire(blocking=False):
            raise OSError("Capacidade de armazenamento ocupada")
        try:
            return operation()
        except AzureError:
            # SDK errors may include storage URLs, query strings or request details.
            raise OSError("Armazenamento privado indisponível") from None
        finally:
            IO_SLOTS.release()

    def put(self, key: str, content: bytes) -> str:
        validate_blob_key(key)
        if len(content) > MAX_OBJECT_BYTES:
            raise ValueError("Objeto excede o limite privado de armazenamento")
        expected = hashlib.sha256(content).hexdigest()

        def write():
            blob = self.container.get_blob_client(key)
            try:
                blob.upload_blob(
                    content,
                    overwrite=False,
                    blob_type="BlockBlob",
                    metadata={"sha256": expected},
                    max_concurrency=1,
                    validate_content=True,
                    timeout=10,
                )
            except ResourceExistsError:
                pass
            actual = hashlib.sha256(self._read(key)).hexdigest()
            if actual != expected:
                raise ValueError("Objeto imutável já existe com conteúdo diferente")
            return actual

        return self._execute(write)

    def read(self, key: str) -> bytes:
        validate_blob_key(key)
        return self._execute(lambda: self._read(key))

    def checksum(self, key: str) -> str:
        return hashlib.sha256(self.read(key)).hexdigest()

    def delete(self, key: str) -> None:
        validate_blob_key(key)

        def remove():
            try:
                self.container.delete_blob(key, delete_snapshots="include", timeout=10)
            except ResourceNotFoundError:
                pass

        self._execute(remove)

    def list_entries(self, prefix: str, cursor: str | None = None, limit: int = 100) -> BlobPage:
        validate_blob_key(prefix)
        if (
            not prefix.endswith("/")
            or not 1 <= limit <= 1000
            or (cursor is not None and len(cursor) > 4096)
        ):
            raise ValueError("Página de objetos inválida")

        def listing():
            pages = self.container.list_blobs(
                name_starts_with=prefix, results_per_page=limit, timeout=10
            ).by_page(continuation_token=cursor)
            page = next(pages, ())
            rows = tuple(BlobEntry(item.name, item.last_modified) for item in page)
            if len(rows) > limit or any(not item.key.startswith(prefix) for item in rows):
                raise OSError("Página de objetos fora do escopo")
            if not isinstance(pages, PageIterator):
                raise OSError("Iterador de objetos incompatível")
            next_cursor: object = pages.continuation_token
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise OSError("Cursor de objetos inválido")
            return BlobPage(rows, next_cursor)

        return self._execute(listing)
