from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from evidencedesk.evidence.storage import PrivateStorage


def test_competing_writers_never_replace_published_content(tmp_path):
    storage = PrivateStorage(tmp_path)
    barrier = Barrier(2)

    def publish(content):
        barrier.wait()
        try:
            storage.put("tenants/test/same-object.txt", content)
            return content
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [b"first content", b"second content"]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert storage.read("tenants/test/same-object.txt") == winners[0]
    storage.put("tenants/test/same-object.txt", winners[0])
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize(
    "key", ["../outside", "dir/../../outside", "/absolute", "C:/path", "dir\\file"]
)
def test_storage_refuses_paths_outside_private_namespace(tmp_path, key):
    with pytest.raises(ValueError):
        PrivateStorage(tmp_path).put(key, b"private")
