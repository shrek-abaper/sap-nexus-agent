#!/usr/bin/env python3
"""Validate evidence grounding of ontology Definitions and object links."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from sap_nexus_agent.evidence_grounding import validate_catalogs  # noqa: E402


def main() -> int:
    violations = validate_catalogs(
        REPO_ROOT,
        REPO_ROOT / "ontology/definitions.yaml",
        REPO_ROOT / "ontology/object-links.yaml",
    )
    if violations:
        for violation in violations:
            print(f"violation: {violation}")
        return 1
    print("Evidence grounding: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
