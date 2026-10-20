"""Master-data snapshot store: importer and search provider.

PostgreSQL is a read-only retrieval projection of SAP master data. Batches
arrive through this governed importer only; the resolution API never
rewrites SAP attributes. See specs/master-data-snapshot-store.
"""

from __future__ import annotations

from .importer import ImportReport, import_snapshot
from .provider import (
    CandidateSet,
    EntityCandidate,
    EntityKey,
    MasterDataProvider,
    ProviderError,
    SearchRequest,
    TrustedScope,
)

__all__ = [
    "CandidateSet",
    "EntityCandidate",
    "EntityKey",
    "ImportReport",
    "MasterDataProvider",
    "ProviderError",
    "SearchRequest",
    "TrustedScope",
    "import_snapshot",
]
