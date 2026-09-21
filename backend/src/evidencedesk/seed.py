"""Carga explícita do laboratório, sem modificar trabalho já existente."""

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from evidencedesk.config import get_settings
from evidencedesk.database import lock_policy, transaction
from evidencedesk.identity.service import PASSWORDS, actor_for_worker
from evidencedesk.incidents.service import create_incident
from evidencedesk.ingestion.contracts import ImportInput, Manifest
from evidencedesk.ingestion.service import (
    create_import,
    finalize_import,
    finish_upload,
    reserve_upload,
)
from evidencedesk.jobs.service import acquire
from evidencedesk.maintenance import initialize_ledger
from evidencedesk.worker import execute_lease

DEMO_PASSWORD = "EvidenceDesk-demo-2026!"
USERS = {
    "aurora": [
        ("ana", "Ana Martins", "analyst"),
        ("bruno", "Bruno Costa", "reviewer"),
        ("admin", "Administrador Aurora", "tenant_admin"),
    ],
    "horizonte": [
        ("carla", "Carla Lima", "analyst"),
        ("diego", "Diego Alves", "reviewer"),
        ("admin", "Administrador Horizonte", "tenant_admin"),
    ],
}


def seed_identity() -> None:
    settings = get_settings()
    if settings.migration_database_url is None:
        raise RuntimeError("O seed explícito exige ED_MIGRATION_DATABASE_URL.")
    owner_engine = create_engine(settings.migration_database_url.get_secret_value())
    for tenant, members in USERS.items():
        with owner_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO tenants(id,name) VALUES(:id,:name) ON CONFLICT DO NOTHING"),
                {
                    "id": tenant,
                    "name": "Aurora Comércio" if tenant == "aurora" else "Horizonte Varejo",
                },
            )
            connection.execute(
                text("SELECT set_config('ed.tenant_id',:tenant,true)"), {"tenant": tenant}
            )
            connection.execute(
                text("INSERT INTO tenant_policy(tenant_id) VALUES(:tenant) ON CONFLICT DO NOTHING"),
                {"tenant": tenant},
            )
            for slug, name, role in members:
                connection.execute(
                    text(
                        "INSERT INTO users(id,tenant_id,email,name,password_hash,role) VALUES(:id,:tenant,:email,:name,:password,:role) ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": f"{tenant}-{slug}",
                        "tenant": tenant,
                        "email": f"{slug}@{tenant}.demo",
                        "name": name,
                        "password": PASSWORDS.hash(DEMO_PASSWORD),
                        "role": role,
                    },
                )
            created = connection.execute(
                text(
                    "INSERT INTO collections(tenant_id,id,name,description) VALUES(:tenant,'commerce-main','Operação de pedidos','Eventos e procedimentos sintéticos do laboratório') ON CONFLICT DO NOTHING RETURNING id"
                ),
                {"tenant": tenant},
            ).first()
            if created:
                for slug, _, _ in members:
                    connection.execute(
                        text(
                            "INSERT INTO collection_grants(tenant_id,collection_id,user_id) VALUES(:tenant,'commerce-main',:user)"
                        ),
                        {"tenant": tenant, "user": f"{tenant}-{slug}"},
                    )
    owner_engine.dispose()


def seed_package(dataset_root: Path, package: dict) -> None:
    tenant = package["tenant"]
    manifest = Manifest.model_validate_json(
        (dataset_root / package["manifest"]).read_text(encoding="utf-8")
    )
    user_id = f"{tenant}-{USERS[tenant][0][0]}"
    with transaction(tenant) as connection:
        actor = actor_for_worker(connection, tenant, user_id)
        policy = lock_policy(connection, tenant, mutation=True)
        batch = (
            connection.execute(
                text(
                    "SELECT id,state FROM import_batches WHERE tenant_id=:tenant AND title=:title ORDER BY created_at LIMIT 1"
                ),
                {"tenant": tenant, "title": manifest.title},
            )
            .mappings()
            .first()
        )
        if batch and batch["state"] == "ready":
            return
        if batch:
            raise RuntimeError(
                f"O pacote {package['directory']} já existe sem concluir; inspecione sua importação."
            )
        import_id = create_import(
            connection, actor, ImportInput(collection_id="commerce-main", manifest=manifest)
        )
    for item in manifest.entries:
        entry = reserve_upload(actor, import_id, item.entry_id)
        content = (dataset_root / package["directory"] / item.filename).read_bytes()
        finish_upload(actor, import_id, entry, content)
    with transaction(tenant) as connection:
        policy = lock_policy(connection, tenant, mutation=True)
        finalize_import(connection, actor, import_id, policy)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        lease = acquire(tenant, "seed-loader")
        if lease:
            execute_lease(lease)
        with transaction(tenant) as connection:
            state = connection.execute(
                text("SELECT state FROM import_batches WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": tenant, "id": import_id},
            ).scalar_one()
            failed = connection.execute(
                text("SELECT state FROM jobs WHERE tenant_id=:tenant AND resource_id=:id"),
                {"tenant": tenant, "id": import_id},
            ).scalar_one()
        if state == "ready":
            print(json.dumps({"package": package["directory"], "state": state}))
            return
        if state in {"rejected", "failed", "cancelled"} or failed in {"failed", "cancelled"}:
            raise RuntimeError(
                f"Pacote {package['directory']} terminou com estado {state}/{failed}."
            )
        time.sleep(0.5)
    raise RuntimeError("Seed excedeu o prazo aguardando publicação.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=Path("/datasets"))
    arguments = parser.parse_args()
    index = json.loads((arguments.dataset_root / "index.json").read_text(encoding="utf-8"))
    seed_identity()
    initialize_ledger()
    for package in index["packages"]:
        seed_package(arguments.dataset_root, package)
    for item in index["incidents"]:
        tenant = item["tenant"]
        with transaction(tenant) as connection:
            actor = actor_for_worker(connection, tenant, f"{tenant}-{USERS[tenant][0][0]}")
            lock_policy(connection, tenant, mutation=True)
            exists = connection.execute(
                text("SELECT id FROM incidents WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": tenant, "id": item["id"]},
            ).first()
            if not exists:
                create_incident(
                    connection,
                    actor,
                    item["title"],
                    "commerce-main",
                    item["window"],
                    item["description"],
                    incident_id=item["id"],
                )
    print(
        json.dumps(
            {
                "state": "seeded",
                "incidents": len(index["incidents"]),
                "origin": "synthetic",
                "model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
