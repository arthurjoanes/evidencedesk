"""Adapter contracts using an explicit SDK double, not cloud integration evidence."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError, ServiceRequestError

from evidencedesk.evidence.azure_blob import MAX_OBJECT_BYTES, AzureBlobStorage


class MemoryContainer:
    def __init__(self):
        self.objects = {}
        self.lock = Lock()
        self.upload_options = []

    def get_blob_client(self, key):
        def upload(content, **options):
            with self.lock:
                self.upload_options.append(options)
                if key in self.objects:
                    raise ResourceExistsError()
                self.objects[key] = content

        def download(**options):
            content = self.objects[key]
            return SimpleNamespace(size=len(content), chunks=lambda: iter([content]))

        return SimpleNamespace(upload_blob=upload, download_blob=download)

    def delete_blob(self, key, **options):
        if key not in self.objects:
            raise ResourceNotFoundError()
        del self.objects[key]


def test_immutable_concurrent_blob_writers_verify_actual_bytes():
    container = MemoryContainer()
    storage = AzureBlobStorage(container)

    def write(content):
        try:
            return storage.put("tenants/a/result.json", content)
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write, [b"first", b"second"]))
    assert results.count("conflict") == 1
    content = storage.read("tenants/a/result.json")
    assert storage.put("tenants/a/result.json", content) == storage.checksum(
        "tenants/a/result.json"
    )
    assert all(
        options["overwrite"] is False and options["max_concurrency"] == 1
        for options in container.upload_options
    )
    storage.delete("tenants/a/result.json")
    storage.delete("tenants/a/result.json")


@pytest.mark.parametrize("key", ["../secret", "/other", "https://host/file", "a?token=sensitive"])
def test_invalid_object_keys_never_reach_sdk(key):
    storage = AzureBlobStorage(MemoryContainer())
    with pytest.raises(ValueError):
        storage.read(key)


def test_oversized_objects_and_sdk_errors_are_bounded_and_sanitized():
    container = MemoryContainer()
    storage = AzureBlobStorage(container)
    container.objects["large"] = b"x" * (MAX_OBJECT_BYTES + 1)
    with pytest.raises(OSError, match="limite"):
        storage.read("large")

    def fail(key):
        raise ServiceRequestError("private Azure diagnostic or credential")

    container.get_blob_client = fail
    with pytest.raises(OSError) as error:
        storage.read("safe-key")
    assert "private Azure" not in str(error.value)


@pytest.mark.parametrize(
    "account", ["https://foreign", "account.blob.core.windows.net", "../account", "Account"]
)
def test_account_url_is_not_caller_controlled(account):
    with pytest.raises(ValueError):
        AzureBlobStorage.managed_identity(account, "private-evidence")
