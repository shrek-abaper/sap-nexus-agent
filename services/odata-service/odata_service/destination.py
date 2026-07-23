"""SAP OData destination configuration loaded from environment variables.

The destination (base URL, credentials, sap-client) is injected via environment
and must NEVER appear in responses, logs, or traces. Credentials are excluded
from the dataclass repr as a defense-in-depth measure.
"""

from __future__ import annotations

import os
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

    Credential env vars (``SAP_URL`` / ``SAP_USER`` / ``SAP_PASSWORD`` /
    ``SAP_CLIENT`` / ``SAP_LANG``) are shared with the JCo path and
    ``sap-sto-create``. ``SAP_ODATA_TIMEOUT_SECONDS`` is OData-specific.
    """
    return Destination(
        base_url=os.environ.get("SAP_URL", "").rstrip("/"),
        sap_client=os.environ.get("SAP_CLIENT", "800"),
        username=os.environ.get("SAP_USER", ""),
        password=os.environ.get("SAP_PASSWORD", ""),
        language=os.environ.get("SAP_LANG", "EN"),
        timeout_seconds=float(os.environ.get("SAP_ODATA_TIMEOUT_SECONDS", "30")),
    )
