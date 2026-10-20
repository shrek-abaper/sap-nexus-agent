"""SAP OData destination configuration loaded from environment variables.

The destination (base URL, credentials, sap-client) is injected via environment
and must NEVER appear in responses, logs, or traces. Credentials are excluded
from the dataclass repr as a defense-in-depth measure.
"""

from __future__ import annotations

import os


def _sap_http_base_url() -> str:
    """Canonical SAP HTTP address: http://<SAP_ASHOST>:<SAP_HTTP_PORT>."""
    host = os.environ.get("SAP_ASHOST", "").strip()
    port = os.environ.get("SAP_HTTP_PORT", "").strip()
    if not host or not port:
        return ""
    return f"http://{host}:{port}"
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Destination:
    base_url: str
    sap_client: str
    username: str = field(repr=False, default="")
    password: str = field(repr=False, default="")
    language: str = "EN"
    timeout_seconds: float = 30.0


def load_destination() -> Destination:
    """Build a :class:`Destination` from environment variables.

    Credential env vars (``SAP_USER`` / ``SAP_PASSWORD`` / ``SAP_CLIENT`` /
    ``SAP_LANG``) are shared with the JCo path and ``sap-sto-create``.
    The address comes from the canonical pair ``SAP_ASHOST`` +
    ``SAP_HTTP_PORT`` (the ICM HTTP port serves OData and SICF on the same
    application server); ``SAP_URL`` no longer exists.
    ``SAP_ODATA_TIMEOUT_SECONDS`` is OData-specific and retained.
    """
    return Destination(
        base_url=_sap_http_base_url(),
        sap_client=os.environ.get("SAP_CLIENT", "800"),
        username=os.environ.get("SAP_USER", ""),
        password=os.environ.get("SAP_PASSWORD", ""),
        language=os.environ.get("SAP_LANG", "EN"),
        timeout_seconds=float(os.environ.get("SAP_ODATA_TIMEOUT_SECONDS", "30")),
    )
