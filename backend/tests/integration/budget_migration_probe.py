"""One-time 0007->0008 migration probe on an explicitly supplied disposable database."""

import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def main():
    engine = create_engine(os.environ["ED_TEST_ADMIN_DATABASE_URL"])
    tenant = "budget-migration-" + uuid4().hex
    parameters = {"tenant": tenant, "user": tenant + "-user"}
    with engine.begin() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0007"
        )
        period = connection.execute(
            text("SELECT date_trunc('month',now() AT TIME ZONE 'UTC')::date")
        ).scalar_one()
        previous = (period - timedelta(days=1)).replace(day=1)
        parameters["previous"] = previous
        for sql in (
            "INSERT INTO tenants(id,name) VALUES(:tenant,'Migration fixture')",
            "INSERT INTO tenant_policy(tenant_id,token_reserved,token_reported) VALUES(:tenant,125,40)",
            "INSERT INTO users(id,tenant_id,email,name,password_hash,role) VALUES(:user,:tenant,:user||'@fixture.invalid','Fixture','not-a-login','analyst')",
            "INSERT INTO collections(tenant_id,id,name) VALUES(:tenant,'collection','Fixture')",
            "INSERT INTO evidence_snapshots(tenant_id,id,collection_id,coverage) VALUES(:tenant,'snapshot','collection','[]')",
            "INSERT INTO incidents(tenant_id,id,collection_id,title,window_from,window_to,time_zone,snapshot_id,created_by) VALUES(:tenant,'incident','collection','Fixture',now(),now()+interval '1 hour','UTC','snapshot',:user)",
            "INSERT INTO investigation_runs(tenant_id,id,incident_id,snapshot_id,created_by,question,policy_revision,model_release) VALUES(:tenant,'run','incident','snapshot',:user,'Fixture',1,'{}')",
            "INSERT INTO provider_calls(tenant_id,id,run_id,job_token,status,reserved_tokens,deployment,created_at) VALUES(:tenant,'unknown','run',1,'unknown',100,'fixture',:previous)",
            "INSERT INTO provider_calls(tenant_id,id,run_id,job_token,status,reserved_tokens,input_tokens,output_tokens,deployment,created_at) VALUES(:tenant,'reported','run',1,'reported',100,10,20,'fixture',:previous)",
        ):
            connection.execute(text(sql), parameters)
    try:
        command.upgrade(Config("backend/alembic.ini"), "0008")
        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    "SELECT period_start,reserved_tokens,reported_tokens FROM token_budget_periods WHERE tenant_id=:tenant ORDER BY period_start"
                ),
                parameters,
            ).all()
            assert rows == [(previous, 100, 30), (period, 25, 10)], rows
            assert connection.execute(
                text(
                    "SELECT sum(reserved_delta),sum(reported_delta) FROM provider_budget_events WHERE tenant_id=:tenant"
                ),
                parameters,
            ).one() == (125, 40)
            assert set(
                connection.execute(
                    text("SELECT budget_period FROM provider_calls WHERE tenant_id=:tenant"),
                    parameters,
                ).scalars()
            ) == {previous}
        report = {
            "status": "passed",
            "migration": "0007_to_0008",
            "known_previous_month": 30,
            "reserved_previous_month": 100,
            "unattributed_reserved_preserved": 25,
            "unattributed_reported_preserved": 10,
            "provider_calls": "fixture_only_no_network",
        }
        output = Path("evals/reports/monthly-budget-migration.json")
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        with engine.begin() as connection:
            for table in (
                "provider_budget_events",
                "provider_calls",
                "token_budget_periods",
                "investigation_runs",
                "incidents",
                "evidence_snapshots",
                "collections",
                "tenant_policy",
                "users",
            ):
                connection.execute(text(f"DELETE FROM {table} WHERE tenant_id=:tenant"), parameters)
            connection.execute(text("DELETE FROM tenants WHERE id=:tenant"), parameters)
        engine.dispose()


if __name__ == "__main__":
    main()
