"""Synthetic configuration only; provider calls use explicit mock transports."""

import os

import pytest
from sqlalchemy.engine import make_url

from evidencedesk.config import get_settings


def pytest_sessionstart(session):
    """Never run database fixtures against the documented demonstration port."""
    for name in (
        "ED_TEST_DATABASE_URL",
        "ED_TEST_ADMIN_DATABASE_URL",
        "ED_MAINTENANCE_TEST_DATABASE_URL",
        "ED_MAINTENANCE_TEST_OWNER_URL",
    ):
        value = os.environ.get(name)
        if value and make_url(value).port == 5546:
            raise pytest.UsageError(
                f"{name} points to demonstration port 5546; use a disposable test database."
            )


@pytest.fixture(autouse=True)
def synthetic_azure_configuration(monkeypatch):
    monkeypatch.setenv(
        "AZURE_OPENAI_BASE_URL", "https://fixture-resource.openai.azure.com/openai/v1/"
    )
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "fixture-deployment")
    monkeypatch.setenv("ED_AZURE_OPENAI_ALLOWED_HOSTS", "fixture-resource.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
