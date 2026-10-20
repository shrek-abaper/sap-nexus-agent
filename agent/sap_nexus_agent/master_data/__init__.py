"""Master-data snapshot store: importer, provider, and maintenance CLI.

PostgreSQL is a read-only retrieval projection of SAP master data. Batches
arrive through this governed importer only; the resolution API never
rewrites SAP attributes. See specs/master-data-snapshot-store.

Imports are lazy (PEP 562) so ``python -m`` on the submodules stays clean.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY = {
    "ImportReport": ".importer",
    "import_snapshot": ".importer",
    "CandidateSet": ".provider",
    "EntityCandidate": ".provider",
    "EntityKey": ".provider",
    "MasterDataProvider": ".provider",
    "ProviderError": ".provider",
    "SearchRequest": ".provider",
    "TrustedScope": ".provider",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
