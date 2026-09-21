"""Create only the isolated upload collection used by the synthetic browser journeys."""

import os

from sqlalchemy import text

from evidencedesk.database import lock_policy, transaction


def main() -> None:
    if (
        os.environ.get("ED_E2E_MODE") != "true"
        or os.environ.get("ED_AI_PROVIDER") != "disabled"
        or os.environ.get("AZURE_OPENAI_API_KEY")
    ):
        raise RuntimeError(
            "Browser fixtures require explicit E2E mode, a disabled provider and no Azure key."
        )
    with transaction("aurora") as connection:
        lock_policy(connection, "aurora", mutation=True)
        users = (
            connection.execute(
                text("""
            SELECT id FROM users WHERE tenant_id='aurora' AND enabled
              AND email IN('ana@aurora.demo','bruno@aurora.demo') ORDER BY id
        """)
            )
            .scalars()
            .all()
        )
        if len(users) != 2:
            raise RuntimeError("The synthetic Aurora seed must exist before browser QA.")
        connection.execute(
            text("""
            INSERT INTO collections(tenant_id,id,name,description)
            VALUES('aurora','qa-imports','Importações de QA','Coleção isolada dos testes de navegador')
            ON CONFLICT(tenant_id,id) DO NOTHING
        """)
        )
        for user in users:
            connection.execute(
                text("""
                INSERT INTO collection_grants(tenant_id,collection_id,user_id)
                VALUES('aurora','qa-imports',:user) ON CONFLICT DO NOTHING
            """),
                {"user": user},
            )
    print("Synthetic browser collection ready; commerce-main unchanged.")


if __name__ == "__main__":
    main()
