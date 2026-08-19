#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from validate_registry_contract import (
    collect_deprecation_warnings,
    count_regex_matchers,
    load_registry_contract,
    load_semantic_type_catalog,
    validate_registry_contract,
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: validate-registry-contract.py <registry-file>", file=sys.stderr)
        return 2
    repo_root = Path(".")
    contract = load_registry_contract(Path(args[0]))
    errors = validate_registry_contract(contract, repo_root=repo_root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    catalog_entries, _catalog_errors = load_semantic_type_catalog(repo_root)
    catalog_count, capability_count = count_regex_matchers(contract, catalog_entries)
    print(
        f"regex matchers in use: {catalog_count + capability_count} "
        f"(semantic-type catalog {catalog_count} + capability-level {capability_count})"
    )
    for warning in collect_deprecation_warnings(contract):
        print(f"warning: {warning}")
    print(f"Registry contract valid: {args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
