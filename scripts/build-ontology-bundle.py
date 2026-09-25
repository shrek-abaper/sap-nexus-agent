#!/usr/bin/env python3
"""Build the ontology bundle from registry YAML into ontology/generated/.

Usage:
    build-ontology-bundle.py            # regenerate artifacts
    build-ontology-bundle.py --check    # fail if committed artifacts are stale

The registry YAML is the single authored source. Exit codes: 0 success /
in sync, 1 stale or build failure, 2 usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "agent")]

from sap_nexus_agent.ontology_codegen import (  # noqa: E402
    build_bundle,
    is_in_sync,
    load_capabilities,
)

GENERATED_DIR = REPO_ROOT / "ontology" / "generated"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    check_only = False
    if args == ["--check"]:
        check_only = True
    elif args:
        print("Usage: build-ontology-bundle.py [--check]", file=sys.stderr)
        return 2

    if check_only:
        in_sync, problems = is_in_sync(GENERATED_DIR)
        if not in_sync:
            for problem in problems:
                print(f"OUT_OF_SYNC {problem}", file=sys.stderr)
            return 1
        print("ontology generated artifacts are in sync")
        return 0

    capabilities = load_capabilities(REPO_ROOT / "registry" / "capabilities.yaml")
    bundle = build_bundle(capabilities)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (GENERATED_DIR / "skos-capabilities.ttl").write_text(
        bundle.skos, encoding="utf-8"
    )
    (GENERATED_DIR / "shacl-inputs.ttl").write_text(
        bundle.shacl, encoding="utf-8"
    )
    manifest = bundle.manifest()
    (GENERATED_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"Ontology bundle written: {GENERATED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
