"""SAP OData HTTP client (read-only GET).

Mirrors the connection layer of ``sap-sto-create`` (sap-client header, Basic
auth, JSON accept, error normalization) but simplified to read-only GET -- no
CSRF token fetch, no deep insert, no write. CSRF for read GET is usually not
required (Design Doc §2.7); a ``_fetch_csrf_token`` hook is retained as an
extension point for the live spike if needed.
"""

from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request
from base64 import b64encode

from .destination import Destination, load_destination


class ODataClient:
    """Thin urllib-based GET client for SAP OData services."""

    def __init__(self, destination: Destination | None = None):
        self._destination = destination or load_destination()
        self._opener = _build_opener(self._destination.base_url)

    def get(
        self,
        service_ref: str,
        entity_set: str,
        filter_str: str,
        top: int | None,
        count: bool,
        select: list[str] | None = None,
    ) -> dict[str, Any]:
        """Issue a GET to ``{base}/sap/opu/odata/sap/{service_ref}/{entity_set}``.

        Returns the parsed JSON body. Raises ``ODataHttpError`` on non-2xx HTTP
        status (after attempting to parse the error body) and propagates network
        errors to the caller.
        """
        return self.get_path(service_ref, entity_set, filter_str, top, count, select)

    def get_path(
        self,
        service_ref: str,
        entity_path: str,
        filter_str: str = "",
        top: int | None = None,
        count: bool = False,
        select: list[str] | None = None,
    ) -> dict[str, Any]:
        """Issue a read-only GET to an entity set or registered navigation path."""
        dest = self._destination
        path = f"/sap/opu/odata/sap/{service_ref}/{entity_path}"
        url = f"{dest.base_url}{path}"
        params: dict[str, str] = {
            "$format": "json",
            "sap-client": dest.sap_client,
        }
        if dest.language:
            params["sap-language"] = dest.language
        if filter_str:
            params["$filter"] = filter_str
        if top is not None:
            params["$top"] = str(top)
        if count:
            params["$count"] = "true"
        if select:
            params["$select"] = ",".join(select)

        full_url = f"{url}?{parse.urlencode(params)}"
        http_request = request.Request(full_url, headers={"Accept": "application/json"})
        if dest.username:
            token = b64encode(f"{dest.username}:{dest.password}".encode("utf-8")).decode("ascii")
            http_request.add_header("Authorization", f"Basic {token}")

        try:
            with self._opener.open(http_request, timeout=dest.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            # SAP OData errors come back as JSON envelopes; surface them for the
            # normalizer to handle as an ODATA_ERROR.
            body = _safe_read(exc)
            if body is not None:
                raise ODataHttpError(f"HTTP {exc.code}", body) from exc
            raise ODataHttpError(f"HTTP {exc.code}", None) from exc

        return json.loads(raw)

    # Extension point: live spike may require a CSRF fetch for some reads.
    def _fetch_csrf_token(self, service_ref: str) -> str:  # pragma: no cover - spike
        raise NotImplementedError


class ODataHttpError(Exception):
    """Raised when SAP responds with a non-2xx status. Carries the parsed body."""

    def __init__(self, message: str, body: dict[str, Any] | None):
        super().__init__(message)
        self.body = body


def _safe_read(exc: error.HTTPError) -> dict[str, Any] | None:
    try:
        return json.loads(exc.read().decode("utf-8"))
    except Exception:
        return None


def _build_opener(base_url: str):
    host = parse.urlsplit(base_url).hostname
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return request.build_opener(request.ProxyHandler({}))
    return request.build_opener()
