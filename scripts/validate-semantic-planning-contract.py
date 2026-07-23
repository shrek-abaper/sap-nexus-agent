#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = REPO_ROOT / "agent"
for path in (str(REPO_ROOT), str(AGENT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from scripts.validate_registry_contract import (  # noqa: E402
    load_registry_contract,
    validate_registry_contract,
)
from sap_nexus_agent.semantic_planning.loader import (  # noqa: E402
    SourceLoadError,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.validation import (  # noqa: E402
    build_semantic_contracts,
)


def main() -> int:
    legacy = load_registry_contract(REPO_ROOT / "registry/capabilities.yaml")
    legacy_errors = validate_registry_contract(legacy, repo_root=REPO_ROOT)
    if legacy_errors:
        for error in legacy_errors:
            print(f"legacy: {error}", file=sys.stderr)
        return 1
    print("Legacy registry contract valid")

    try:
        sources = load_semantic_sources(REPO_ROOT)
    except SourceLoadError as exc:
        print(f"SCHEMA_INVALID {exc.path}: {exc.message}", file=sys.stderr)
        return 1
    result = build_semantic_contracts(sources)
    if not result.report.valid:
        for issue in result.report.issues:
            print(f"{issue.code} {issue.path}: {issue.message}", file=sys.stderr)
        return 1
    assert result.snapshot is not None
    print(f"Semantic planning contract valid: snapshotId={result.snapshot.snapshot_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
