"""Tests for Destination env-var loading.

Env var names are aligned with sap-sto-create (SAP_URL / SAP_USER / SAP_PASSWORD
/ SAP_CLIENT / SAP_LANG) so credentials are shared across OData + JCo paths.
SAP_ODATA_TIMEOUT_SECONDS is OData-specific and retained.
"""

from __future__ import annotations

import os

import pytest

from odata_service.destination import Destination, load_destination


@pytest.fixture
def _clean_env(monkeypatch):
    """Remove all SAP_* env vars so tests are deterministic."""
    for key in list(os.environ):
        if key.startswith("SAP_"):
            monkeypatch.delenv(key, raising=False)
    yield


def test_load_destination_reads_aligned_env_vars(_clean_env, monkeypatch):
    monkeypatch.setenv("SAP_URL", "https://sap.example.local:44300/")
    monkeypatch.setenv("SAP_CLIENT", "100")
    monkeypatch.setenv("SAP_USER", "odata_user")
    monkeypatch.setenv("SAP_PASSWORD", "secret")
    monkeypatch.setenv("SAP_LANG", "ZH")
    monkeypatch.setenv("SAP_ODATA_TIMEOUT_SECONDS", "45")

    dest = load_destination()

    assert dest.base_url == "https://sap.example.local:44300"  # trailing slash stripped
    assert dest.sap_client == "100"
    assert dest.username == "odata_user"
    assert dest.password == "secret"
    assert dest.language == "ZH"
    assert dest.timeout_seconds == 45.0


def test_load_destination_defaults(_clean_env, monkeypatch):
    monkeypatch.setenv("SAP_URL", "https://sap.example.local")

    dest = load_destination()

    assert dest.base_url == "https://sap.example.local"
    assert dest.sap_client == "800"
    assert dest.username == ""
    assert dest.password == ""
    assert dest.language == "EN"
    assert dest.timeout_seconds == 30.0


def test_destination_password_not_in_repr():
    """Password must be excluded from repr (defense-in-depth redaction)."""
    dest = Destination(
        base_url="https://sap.example.local",
        sap_client="100",
        username="user",
        password="super_secret_value",
    )
    repr_str = repr(dest)
    assert "super_secret_value" not in repr_str
    assert "password" not in repr_str.lower()
