from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_manual_workflow import ORIGIN, create_import

from evidencedesk.database import transaction
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.ingestion import routes

pytestmark = pytest.mark.integration


def test_competing_put_and_finalize_cannot_seal_an_upload_in_progress(workspace, monkeypatch):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    body = b"# Concurrency fixture\nThe original is immutable."
    batch = create_import(client, tenant, body)
    url = f"/api/v1/imports/{batch}"
    waiting, release = Event(), Event()
    finish = routes.finish_upload

    def pause_after_body(*args):
        waiting.set()
        assert release.wait(10)
        return finish(*args)

    monkeypatch.setattr(routes, "finish_upload", pause_after_body)
    with TestClient(workspace["app"], base_url=ORIGIN) as competitor:
        competitor.cookies.update(client.cookies)
        competitor.headers.update(client.headers)
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(
                client.put,
                url + "/files/manual",
                content=body,
                headers={"Content-Type": "text/markdown"},
            )
            try:
                assert waiting.wait(5)
                second = competitor.put(
                    url + "/files/manual", content=body, headers={"Content-Type": "text/markdown"}
                )
                assert second.status_code == 409, second.text
                assert second.json()["error"]["code"] == "upload_in_progress"
                assert competitor.post(url + "/finalize").status_code == 409
            finally:
                release.set()
            response = pending.result(timeout=10)
            assert response.status_code == 200, response.text
    assert (
        client.put(
            url + "/files/manual", content=body, headers={"Content-Type": "text/markdown"}
        ).status_code
        == 200
    )
    assert client.post(url + "/finalize").status_code == 202
    with transaction(tenant) as connection:
        keys = (
            connection.execute(
                text(
                    "SELECT object_key FROM import_entries WHERE tenant_id=:tenant AND batch_id=:batch"
                ),
                {"tenant": tenant, "batch": batch},
            )
            .scalars()
            .all()
        )
        assert len(keys) == 1
        assert connection.execute(
            text("SELECT storage_reserved FROM tenant_policy WHERE tenant_id=:tenant"),
            {"tenant": tenant},
        ).scalar_one() == len(body)
    assert PrivateStorage().read(keys[0]) == body
