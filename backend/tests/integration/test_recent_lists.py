"""The public lists use immutable creation dates and keep ACL-bound cursors."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from test_manual_workflow import create_import, create_incident, import_document

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("resource", ["imports", "incidents"])
def test_recent_lists_keep_stable_keyset_across_new_items_and_timestamp_ties(workspace, resource):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    other_client = workspace["client"](tenant_index=1)
    if resource == "incidents":
        import_document(client, tenant)

    def create():
        if resource == "incidents":
            return create_incident(client)
        return create_import(client, tenant, b"Package for chronological pagination")

    ids = [create() for _ in range(4)]
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    table = "import_batches" if resource == "imports" else "incidents"
    with workspace["admin"].begin() as connection:
        for index, item_id in enumerate(ids):
            connection.execute(
                text(f"UPDATE {table} SET created_at=:created WHERE tenant_id=:tenant AND id=:id"),
                {
                    "tenant": tenant,
                    "id": item_id,
                    "created": created_at + timedelta(days=index > 0),
                },
            )
    expected = sorted(ids[1:], reverse=True) + ids[:1]
    url = f"/api/v1/{resource}"
    first = client.get(url, params={"limit": 2})
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert [item["id"] for item in first_page["items"]] == expected[:2]
    cursor = first_page["next_cursor"]
    assert cursor is not None

    # A new item belongs above the cursor and must neither repeat nor displace
    # the remaining older rows while the user continues this traversal.
    newest = create()
    if resource == "incidents":
        with workspace["admin"].begin() as connection:
            connection.execute(
                text("UPDATE incidents SET updated_at=now() WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": tenant, "id": expected[-1]},
            )
    second = client.get(url, params={"limit": 2, "cursor": cursor}).json()
    assert [item["id"] for item in second["items"]] == expected[2:]
    assert second["next_cursor"] is None
    assert client.get(url, params={"limit": 1}).json()["items"][0]["id"] == newest
    assert other_client.get(url, params={"cursor": cursor}).status_code == 409
    assert other_client.get(url).json()["items"] == []

    with workspace["admin"].begin() as connection:
        connection.execute(
            text("DELETE FROM collection_grants WHERE tenant_id=:tenant AND user_id=:user"),
            {"tenant": tenant, "user": tenant + "-author"},
        )
    assert client.get(url, params={"cursor": cursor}).json()["items"] == []
