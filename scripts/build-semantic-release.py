#!/usr/bin/env python3
"""Build the SemanticRelease v1 package into ontology/generated/.

Usage:
    build-semantic-release.py            # regenerate semantic-release.json
    build-semantic-release.py --check    # fail if the committed package is stale

The authored ontology/registry YAML is the single source. Exit codes:
0 success / in sync, 1 stale or build failure, 2 usage error.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "agent")]

from sap_nexus_agent.semantic_release.builder import (  # noqa: E402
    build_semantic_release,
)

GENERATED_DIR = REPO_ROOT / "ontology" / "generated"
PACKAGE_PATH = GENERATED_DIR / "semantic-release.json"


def _serialize(document: dict) -> bytes:
    return (
        json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _render() -> bytes:
    return _serialize(build_semantic_release(REPO_ROOT).to_dict())


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args == ["--check"]:
        expected = _render()
        if not PACKAGE_PATH.exists():
            print("OUT_OF_SYNC semantic-release.json missing", file=sys.stderr)
            return 1
        if PACKAGE_PATH.read_bytes() != expected:
            print("OUT_OF_SYNC semantic-release.json content differs", file=sys.stderr)
            return 1
        print("semantic release package is in sync")
        return 0
    if args:
        print("Usage: build-semantic-release.py [--check]", file=sys.stderr)
        return 2

    content = _render()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = PACKAGE_PATH.with_suffix(".json.tmp")
    tmp_path.write_bytes(content)
    os.replace(tmp_path, PACKAGE_PATH)
    print(f"wrote {PACKAGE_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
