"""Real PostgreSQL/pgvector + app RLS role; all records belong to disposable test tenants."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from evidencedesk.errors import Problem
from evidencedesk.identity.service import Actor
from evidencedesk.retrieval.lexical import LEXEME_PLAN_SQL
from evidencedesk.retrieval.repository import index_snapshot, search_evidence

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.fixture
def database():
    admin_url = os.environ.get(
        "ED_TEST_ADMIN_DATABASE_URL",
        "postgresql+psycopg://postgres:ed_admin_local_demo@127.0.0.1:5546/evidencedesk",
    )
    app_url = os.environ.get(
        "ED_TEST_DATABASE_URL",
        "postgresql+psycopg://ed_app:ed_app_local_demo@127.0.0.1:5546/evidencedesk",
    )
    admin, app = (
        create_engine(admin_url, pool_size=1, max_overflow=0),
        create_engine(app_url, pool_size=1, max_overflow=0),
    )
    tag = "retrieval-test-" + uuid4().hex
    tenants = [tag + "-a", tag + "-b"]
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT 1 FROM evidence LIMIT 1"))
    except OperationalError:
        admin.dispose()
        app.dispose()
        pytest.skip("PostgreSQL de integração não está disponível.")

    with admin.begin() as connection:
        for tenant in tenants:
            connection.execute(
                text("INSERT INTO tenants(id,name) VALUES(:tenant,'Retrieval fixture')"),
                {"tenant": tenant},
            )
            connection.execute(
                text("INSERT INTO tenant_policy(tenant_id) VALUES(:tenant)"), {"tenant": tenant}
            )
            connection.execute(
                text("""
                INSERT INTO users(id,tenant_id,email,name,password_hash,role)
                VALUES(:user,:tenant,:email,'Fixture user','not-a-login-hash','analyst')
            """),
                {"user": tenant + "-user", "tenant": tenant, "email": tenant + "@fixture.invalid"},
            )
            connection.execute(
                text(
                    "INSERT INTO collections(tenant_id,id,name) VALUES(:tenant,'collection','Fixture collection')"
                ),
                {"tenant": tenant},
            )
            connection.execute(
                text(
                    "INSERT INTO collection_grants(tenant_id,collection_id,user_id) VALUES(:tenant,'collection',:user)"
                ),
                {"tenant": tenant, "user": tenant + "-user"},
            )
            connection.execute(
                text(
                    "INSERT INTO evidence_snapshots(tenant_id,id,collection_id,coverage) VALUES(:tenant,'snapshot','collection','[]')"
                ),
                {"tenant": tenant},
            )
            connection.execute(
                text("""
                INSERT INTO incidents(tenant_id,id,collection_id,title,window_from,window_to,time_zone,snapshot_id,created_by)
                VALUES(:tenant,'incident','collection','Fixture incident',:start,:end,'UTC','snapshot',:user)
            """),
                {
                    "tenant": tenant,
                    "start": NOW,
                    "end": NOW + timedelta(hours=1),
                    "user": tenant + "-user",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO incident_members(tenant_id,incident_id,user_id) VALUES(:tenant,'incident',:user)"
                ),
                {"tenant": tenant, "user": tenant + "-user"},
            )
            for evidence_id, role, start, end in [
                ("current", "applicable_procedure", NOW - timedelta(days=1), None),
                (
                    "historical",
                    "historical_artifact",
                    NOW - timedelta(days=5),
                    NOW - timedelta(days=1),
                ),
                ("retrospective", "retrospective_context", NOW + timedelta(days=1), None),
                (
                    "obsolete-norm",
                    "applicable_procedure",
                    NOW - timedelta(days=10),
                    NOW - timedelta(days=2),
                ),
                ("future-norm", "applicable_procedure", NOW + timedelta(days=2), None),
            ]:
                body = f"Pagamento confirmado no procedimento de {tenant}. Evidência {evidence_id}."
                connection.execute(
                    text("""
                    INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,source_system,
                                         temporal_role,valid_from,valid_until,canonical_text)
                    VALUES(:tenant,:id,'collection','document_span',:id,'1',:sha,'knowledge',:role,:start,:end,:body)
                """),
                    {
                        "tenant": tenant,
                        "id": evidence_id,
                        "sha": hashlib.sha256(body.encode()).hexdigest(),
                        "role": role,
                        "start": start,
                        "end": end,
                        "body": body,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO snapshot_members(tenant_id,snapshot_id,evidence_id) VALUES(:tenant,'snapshot',:id)"
                    ),
                    {"tenant": tenant, "id": evidence_id},
                )
    actor = Actor(
        tenants[0] + "-user",
        tenants[0],
        "Fixture user",
        "Fixture tenant",
        "analyst",
        "",
        NOW + timedelta(days=1),
    )
    try:
        yield admin, app, actor, tenants
    finally:
        with admin.begin() as connection:
            for table in (
                "snapshot_mappings",
                "snapshot_members",
                "evidence",
                "incident_members",
                "incidents",
                "collection_grants",
                "evidence_snapshots",
                "collections",
                "tenant_policy",
                "users",
                "tenants",
            ):
                # Fixed table names; bound IDs are the exact fixture-created namespaces.
                column = "id" if table == "tenants" else "tenant_id"
                for tenant in tenants:
                    connection.execute(
                        text(f"DELETE FROM {table} WHERE {column}=:tenant"), {"tenant": tenant}
                    )
        admin.dispose()
        app.dispose()


def tenant_connection(app, actor):
    connection = app.connect()
    transaction = connection.begin()
    connection.execute(
        text("SELECT set_config('ed.tenant_id',:tenant,true)"), {"tenant": actor.tenant_id}
    )
    return connection, transaction


def test_fts_is_real_and_never_returns_other_tenant_or_inapplicable_norms(database):
    _, app, actor, tenants = database
    connection, transaction = tenant_connection(app, actor)
    try:
        result = search_evidence(connection, actor, "incident", "snapshot", "pagamento")
        assert {item.evidence_id for item in result} == {"current", "historical", "retrospective"}
        assert all(tenants[0] in item.text and tenants[1] not in item.text for item in result)
        assert next(item for item in result if item.evidence_id == "retrospective").valid_from > NOW
    finally:
        transaction.rollback()
        connection.close()


def test_natural_language_planner_normalizes_bounds_and_retrieves_without_all_terms(database):
    _, app, actor, _ = database
    connection, transaction = tenant_connection(app, actor)
    try:
        query = (
            "Quais documentos ajudam a investigar o pagamento confirmado sem presumir causalidade?"
        )
        result = search_evidence(connection, actor, "incident", "snapshot", query)
        assert {item.evidence_id for item in result} == {"current", "historical", "retrospective"}
        planned = connection.execute(
            text(LEXEME_PLAN_SQL), {"query": " ".join(f"termo{x}" for x in range(50))}
        ).scalar_one()
        assert planned.count(" | ") == 15
        assert connection.execute(text(LEXEME_PLAN_SQL), {"query": "de a o e"}).scalar_one() == ""
        safe = connection.execute(
            text(LEXEME_PLAN_SQL), {"query": "pagamento'); DROP TABLE evidence;--"}
        ).scalar_one()
        connection.execute(text("SELECT to_tsquery('simple',:query)"), {"query": safe}).scalar_one()
        assert connection.execute(text("SELECT count(*) FROM evidence")).scalar_one() > 0
    finally:
        transaction.rollback()
        connection.close()


def test_temporal_purpose_is_a_sql_filter(database):
    _, app, actor, _ = database
    connection, transaction = tenant_connection(app, actor)
    try:
        result = search_evidence(
            connection, actor, "incident", "snapshot", "pagamento", purpose="applicable_procedure"
        )
        assert [item.evidence_id for item in result] == ["current"]
    finally:
        transaction.rollback()
        connection.close()


def test_grant_revocation_denies_search_instead_of_returning_cached_content(database):
    admin, app, actor, _ = database
    with admin.begin() as connection:
        connection.execute(
            text("DELETE FROM collection_grants WHERE tenant_id=:tenant"),
            {"tenant": actor.tenant_id},
        )
    connection, transaction = tenant_connection(app, actor)
    try:
        with pytest.raises(Problem) as caught:
            search_evidence(connection, actor, "incident", "snapshot", "pagamento")
        assert caught.value.status == 404
    finally:
        transaction.rollback()
        connection.close()


def test_vector_mode_does_not_silently_search_partial_index(database):
    _, app, actor, _ = database
    connection, transaction = tenant_connection(app, actor)
    try:
        with pytest.raises(Problem) as caught:
            search_evidence(
                connection,
                actor,
                "incident",
                "snapshot",
                "pagamento",
                mode="vector",
                query_embedding=[1.0] + [0.0] * 383,
                embedding_revision="fixture-v1",
            )
        assert caught.value.code == "embedding_index_incomplete"
    finally:
        transaction.rollback()
        connection.close()


class FixtureEncoder:
    dimensions, batch_size = 384, 2

    def __init__(self, app):
        self.app = app
        self.calls = 0

    def encode_passages(self, passages):
        assert self.app.pool.checkedout() == 0, "Inference must not hold a database connection."
        self.calls += 1
        return [[1.0] + [0.0] * 383 for _ in passages]


def test_indexing_releases_connection_and_real_pgvector_hybrid_search_works(database):
    _, app, actor, _ = database
    encoder = FixtureEncoder(app)
    result = index_snapshot(app, actor, "snapshot", encoder, embedding_revision="fixture-v1")
    assert result.complete and result.indexed_now == 5
    assert encoder.calls == 3
    again = index_snapshot(app, actor, "snapshot", encoder, embedding_revision="fixture-v1")
    assert again.indexed_now == 0
    connection, transaction = tenant_connection(app, actor)
    try:
        result = search_evidence(
            connection,
            actor,
            "incident",
            "snapshot",
            "pagamento",
            mode="hybrid",
            query_embedding=[1.0] + [0.0] * 383,
            embedding_revision="fixture-v1",
        )
        assert {item.evidence_id for item in result} == {"current", "historical", "retrospective"}
    finally:
        transaction.rollback()
        connection.close()


def test_revocation_during_encode_prevents_index_write(database):
    admin, app, actor, _ = database

    class RevokingEncoder(FixtureEncoder):
        def encode_passages(self, passages):
            vectors = super().encode_passages(passages)
            with admin.begin() as connection:
                connection.execute(
                    text("UPDATE tenant_policy SET revision=revision+1 WHERE tenant_id=:tenant"),
                    {"tenant": actor.tenant_id},
                )
                connection.execute(
                    text("DELETE FROM collection_grants WHERE tenant_id=:tenant"),
                    {"tenant": actor.tenant_id},
                )
            return vectors

    with pytest.raises(Problem):
        index_snapshot(
            app, actor, "snapshot", RevokingEncoder(app), embedding_revision="fixture-v1"
        )
    with admin.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM evidence WHERE tenant_id=:tenant AND embedding IS NOT NULL"),
            {"tenant": actor.tenant_id},
        ).scalar_one()
    assert count == 0


def test_revision_change_requires_new_corpus_instead_of_overwriting_vectors(database):
    _, app, actor, _ = database
    encoder = FixtureEncoder(app)
    index_snapshot(app, actor, "snapshot", encoder, embedding_revision="fixture-v1")
    with pytest.raises(Problem) as caught:
        index_snapshot(app, actor, "snapshot", encoder, embedding_revision="fixture-v2")
    assert caught.value.code == "embedding_revision_conflict"


def test_incident_scope_uses_observation_only_when_occurrence_is_unknown(database):
    from evidencedesk.incidents.service import load_reconciliation
    from evidencedesk.reconciliation import EventObservation, OrderSnapshot

    admin, app, actor, _ = database
    expected_ids = {"scope-inside", "scope-unknown-inside", "scope-late"}
    cases = [
        ("scope-inside", NOW + timedelta(seconds=10), NOW + timedelta(seconds=11)),
        ("scope-unknown-inside", None, NOW + timedelta(seconds=20)),
        ("scope-unknown-other-day", None, NOW - timedelta(days=1)),
        ("scope-late", NOW + timedelta(seconds=30), NOW + timedelta(days=2)),
        ("scope-old-recent-observation", NOW - timedelta(days=1), NOW + timedelta(seconds=40)),
        ("scope-unassigned", None, None),
    ]
    records = []
    for evidence_id, occurred, observed in cases:
        event = EventObservation(
            source_system="payments",
            source_event_id=evidence_id,
            evidence_id=evidence_id,
            order_reference="source-order",
            event_type="payment.confirmed" if evidence_id == "scope-inside" else "audit.observed",
            occurred_at=occurred,
            observed_at=observed,
            ingested_at=NOW + timedelta(days=20),
            source_file_sha256="a" * 64,
            line_number=1,
        )
        records.append(("source_event", event.model_dump(mode="json")))
    snapshot = OrderSnapshot(
        evidence_id="scope-snapshot",
        source_system="orders",
        snapshot_id="source-snapshot",
        order_reference="source-order",
        status="pending_payment",
        as_of=NOW + timedelta(minutes=5),
        source_file_sha256="a" * 64,
        line_number=1,
    )
    records.append(("order_snapshot", snapshot.model_dump(mode="json")))
    coverage = [
        {
            "source_system": source,
            "status": "complete",
            "from": NOW.isoformat(),
            "to": (NOW + timedelta(hours=1)).isoformat(),
            "clock_uncertainty_ms": 0,
        }
        for source in ("payments", "orders")
    ]
    coverage.append(
        {
            "source_system": "payments",
            "status": "unknown",
            "from": (NOW - timedelta(days=2)).isoformat(),
            "to": (NOW - timedelta(days=1)).isoformat(),
            "clock_uncertainty_ms": None,
        }
    )
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE evidence_snapshots SET coverage=CAST(:coverage AS jsonb) WHERE tenant_id=:tenant AND id='snapshot'"
            ),
            {"tenant": actor.tenant_id, "coverage": json.dumps(coverage)},
        )
        for source in ("payments", "orders"):
            connection.execute(
                text("""
                INSERT INTO snapshot_mappings(tenant_id,snapshot_id,source_system,source_order_reference,order_reference)
                VALUES(:tenant,'snapshot',:source,'source-order','canonical-order')
            """),
                {"tenant": actor.tenant_id, "source": source},
            )
        for kind, record in records:
            canonical = json.dumps(record)
            connection.execute(
                text("""
                INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,source_system,
                                     temporal_role,canonical_text,record)
                VALUES(:tenant,:id,'collection',:kind,:id,'1',:sha,:source,'historical_artifact',:canonical,CAST(:record AS jsonb))
            """),
                {
                    "tenant": actor.tenant_id,
                    "id": record["evidence_id"],
                    "kind": kind,
                    "sha": "a" * 64,
                    "source": record["source_system"],
                    "canonical": canonical,
                    "record": canonical,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO snapshot_members(tenant_id,snapshot_id,evidence_id) VALUES(:tenant,'snapshot',:id)"
                ),
                {"tenant": actor.tenant_id, "id": record["evidence_id"]},
            )
    connection, transaction = tenant_connection(app, actor)
    try:
        result = load_reconciliation(connection, actor, "incident", "snapshot")
    finally:
        transaction.rollback()
        connection.close()
    assert {row.evidence_id for row in result.timeline} == expected_ids
    unknown = next(row for row in result.timeline if row.evidence_id == "scope-unknown-inside")
    assert unknown.occurred_at is None and unknown.temporal_quality == "unknown"
    late = next(row for row in result.timeline if row.evidence_id == "scope-late")
    assert late.observed_at > NOW + timedelta(days=1)
    assert len(result.coverage) == 2
    assert all(item.clock_uncertainty_ms == 0 for item in result.coverage)
    assert any(
        fact.rule_code == "payment_snapshot_mismatch" and fact.status == "divergence"
        for fact in result.divergences
    )
