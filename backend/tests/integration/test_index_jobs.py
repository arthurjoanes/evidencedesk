"""Durable index admission and fencing, with simulated vectors explicitly isolated."""

import pytest
from sqlalchemy import text
from test_manual_workflow import import_document

from evidencedesk.config import get_settings
from evidencedesk.database import get_engine, lock_policy, transaction
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.jobs.service import acquire, cancel
from evidencedesk.retrieval import jobs
from evidencedesk.worker import execute_lease

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("cancel_during_inference", [False, True])
def test_index_is_idempotent_and_cancelled_work_cannot_publish(
    workspace, monkeypatch, cancel_during_inference
):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    snapshot = import_document(client, tenant)
    monkeypatch.setenv("ED_MODEL_SERVICE_TOKEN", "fixture-model-token-at-least-24-characters")
    get_settings.cache_clear()
    url = f"/api/v1/evidence-snapshots/{snapshot}/index"
    initial = client.get(url).json()
    assert initial["indexing_enabled"] and initial["disabled_reason"] is None
    assert not initial["complete"] and initial["indexed_documents"] == 0
    admitted = client.post(url, headers={"Idempotency-Key": "index-fixture"})
    assert admitted.status_code == 202, admitted.text
    assert client.post(url, headers={"Idempotency-Key": "index-fixture"}).json() == admitted.json()
    assert workspace["client"](1).get(url).status_code == 404
    lease = acquire(tenant, "index-fixture")
    assert lease and lease.kind == "index_snapshot"

    class FixtureEncoder:
        dimensions = 384
        batch_size = 8

        def encode_passages(self, passages):
            assert get_engine().pool.checkedout() == 0
            if cancel_during_inference:
                with transaction(tenant) as connection:
                    lock_policy(connection, tenant)
                    actor = actor_for_worker(connection, tenant, tenant + "-author")
                    cancel(connection, actor, snapshot)
            return [[1.0] + [0.0] * 383 for _ in passages]

    monkeypatch.setattr(jobs, "RemoteModels", lambda client, token: FixtureEncoder())
    execute_lease(lease)
    result = client.get(url).json()
    assert result["complete"] is not cancel_during_inference
    assert result["job"]["state"] == ("cancelled" if cancel_during_inference else "succeeded")
    with transaction(tenant) as connection:
        published = connection.execute(
            text("SELECT count(*) FROM evidence WHERE tenant_id=:tenant AND embedding IS NOT NULL"),
            {"tenant": tenant},
        ).scalar_one()
    assert published == (0 if cancel_during_inference else initial["total_documents"])


def test_index_capability_does_not_depend_on_lexical_mode(workspace, monkeypatch):
    tenant = workspace["tenants"][0]
    client = workspace["client"]()
    snapshot = import_document(client, tenant)
    monkeypatch.setenv("ED_MODEL_SERVICE_TOKEN", "")
    monkeypatch.setenv("ED_RETRIEVAL_MODE", "lexical")
    get_settings.cache_clear()
    url = f"/api/v1/evidence-snapshots/{snapshot}/index"
    result = client.get(url).json()
    assert result["indexing_enabled"] is False
    assert result["disabled_reason"] == "O serviço privado de modelos não está configurado."
    monkeypatch.setenv("ED_MODEL_SERVICE_TOKEN", "fixture-model-token-at-least-24-characters")
    get_settings.cache_clear()
    assert client.get(url).json()["indexing_enabled"] is True
